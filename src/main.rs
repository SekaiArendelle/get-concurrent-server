use axum::{
    Router,
    extract::State,
    middleware::{self, Next},
    response::Response,
    routing::get,
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use std::time::Duration;

use rand::Rng;
use rand_distr::Normal;

#[derive(Clone)]
struct AppState {
    counter: Arc<AtomicUsize>,
}

struct DecGuard<'a> {
    counter: &'a AtomicUsize,
}

impl Drop for DecGuard<'_> {
    fn drop(&mut self) {
        self.counter.fetch_sub(1, Ordering::Relaxed);
    }
}

async fn track_concurrency(
    State(state): State<AppState>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    state.counter.fetch_add(1, Ordering::Relaxed);
    let _guard = DecGuard { counter: &state.counter };
    next.run(request).await
}

async fn concurrent(State(state): State<AppState>) -> String {
    state.counter.load(Ordering::Relaxed).to_string()
}

async fn slow(State(state): State<AppState>) -> String {
    let normal = Normal::new(1000.0, 200.0).unwrap();
    let ms = rand::thread_rng().sample::<f64, _>(normal).max(0.0) as u64;
    tokio::time::sleep(Duration::from_millis(ms)).await;
    state.counter.load(Ordering::Relaxed).to_string()
}

#[tokio::main]
async fn main() {
    let state = AppState {
        counter: Arc::new(AtomicUsize::new(0)),
    };

    let app = Router::new()
        .route("/concurrent", get(concurrent))
        .route("/slow", get(slow))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            track_concurrency,
        ))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .unwrap();
    axum::serve(listener, app).await.unwrap();
}

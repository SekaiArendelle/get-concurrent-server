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

#[derive(Clone)]
struct AppState {
    counter: Arc<AtomicUsize>,
}

async fn track_concurrency(
    State(state): State<AppState>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    state.counter.fetch_add(1, Ordering::Relaxed);
    let response = next.run(request).await;
    state.counter.fetch_sub(1, Ordering::Relaxed);
    response
}

async fn concurrent(State(state): State<AppState>) -> String {
    state.counter.load(Ordering::Relaxed).to_string()
}

async fn slow() -> &'static str {
    tokio::time::sleep(Duration::from_secs(10)).await;
    "done"
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

    let listener = tokio::net::TcpListener::bind("127.0.0.1:3000")
        .await
        .unwrap();
    axum::serve(listener, app).await.unwrap();
}

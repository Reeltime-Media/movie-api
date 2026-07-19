"""Baray payment test page — BARAY DISABLED (router not mounted in main.py).

Kept in the codebase for when Baray checkout is re-enabled.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.dependencies import DBSession
from app.models.content import Content
from app.models.payment_intent import PaymentIntent
from app.models.user import User
from app.services.payment import checkout_url, create_intent, format_usd

router = APIRouter(prefix="/payment-test", tags=["payment-test"])


@router.get("", response_class=HTMLResponse)
async def payment_test_page():
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Reeltime Payment Test</title>
    <style>
      :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      body { margin: 0; min-height: 100vh; background: #09090b; color: #f4f4f5; }
      main { width: min(920px, calc(100vw - 32px)); margin: 40px auto; }
      .hero { margin-bottom: 24px; padding: 24px; border: 1px solid #27272a; border-radius: 18px; background: linear-gradient(135deg, #18181b, #0f172a); }
      h1 { margin: 0 0 8px; font-size: 30px; }
      p { margin: 0; color: #a1a1aa; line-height: 1.6; }
      .warning { margin-top: 14px; color: #fde68a; font-size: 14px; }
      .grid { display: grid; gap: 14px; }
      .movie { display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center; padding: 18px; border: 1px solid #27272a; border-radius: 16px; background: #18181b; }
      .title { font-weight: 700; font-size: 17px; }
      .meta { margin-top: 5px; color: #a1a1aa; font-size: 14px; }
      button { border: 0; border-radius: 999px; padding: 10px 16px; background: #7c3aed; color: white; font-weight: 700; cursor: pointer; }
      button:disabled { cursor: wait; opacity: .55; }
      pre { overflow: auto; margin-top: 20px; padding: 16px; border-radius: 14px; background: #030712; color: #d4d4d8; }
      a { color: #c4b5fd; }
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <h1>Reeltime Payment Test</h1>
        <p>This no-auth page creates a real Baray movie payment intent for one of your current movie records.</p>
        <p class="warning">Use a tiny-priced movie. Your Baray key appears to be live mode.</p>
      </section>
      <section id="movies" class="grid">Loading movies...</section>
      <pre id="log">Ready.</pre>
    </main>
    <script>
      const moviesEl = document.querySelector("#movies");
      const logEl = document.querySelector("#log");

      function log(value) {
        logEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      }

      async function loadMovies() {
        const res = await fetch("/payment-test/movies");
        const movies = await res.json();
        if (!res.ok) throw new Error(movies.detail || "Could not load movies");
        if (!movies.length) {
          moviesEl.textContent = "No movies with a price were found.";
          return;
        }
        moviesEl.innerHTML = movies.map((movie) => `
          <article class="movie">
            <div>
              <div class="title"></div>
              <div class="meta">Movie ID: ${movie.id}</div>
              <div class="meta">Price: $${movie.price_usd} · Status: ${movie.status}</div>
            </div>
            <button data-id="${movie.id}">Pay with Baray</button>
          </article>
        `).join("");
        moviesEl.querySelectorAll(".movie").forEach((article, index) => {
          const titleEl = article.querySelector(".title");
          if (titleEl) titleEl.textContent = movies[index].title;
        });
      }

      moviesEl.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-id]");
        if (!button) return;
        button.disabled = true;
        log("Creating Baray payment intent...");
        try {
          const res = await fetch(`/payment-test/movies/${button.dataset.id}/intent`, { method: "POST" });
          const intent = await res.json();
          if (!res.ok) throw new Error(intent.detail || "Could not create payment intent");
          log(intent);
          window.location.href = intent.checkout_url;
        } catch (error) {
          log(error instanceof Error ? error.message : String(error));
          button.disabled = false;
        }
      });

      loadMovies().catch((error) => log(error.message));
    </script>
  </body>
</html>
        """
    )


@router.get("/movies")
async def list_payment_test_movies(db: DBSession):
    result = await db.execute(
        select(Content)
        .where(
            Content.type == "single",
            Content.is_published.is_(True),
            Content.price_usd.is_not(None),
        )
        .order_by(Content.created_at.desc())
    )
    return [
        {
            "id": movie.id,
            "title": movie.title,
            "price_usd": format_usd(movie.price_usd),
            "status": movie.status,
        }
        for movie in result.scalars().all()
        if movie.price_usd is not None
    ]


@router.post("/movies/{content_id}/intent")
async def create_payment_test_movie_intent(
    content_id: uuid.UUID,
    request: Request,
    db: DBSession,
):
    user_result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.created_at)
    )
    test_user = user_result.scalars().first()
    if not test_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create at least one active user before testing payments",
        )

    movie_result = await db.execute(
        select(Content).where(
            Content.id == content_id,
            Content.type == "single",
        )
    )
    movie = movie_result.scalar_one_or_none()
    if not movie or movie.price_usd is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with a price was not found",
        )

    order_id = f"movie-test-{uuid.uuid4().hex}"
    baray_intent = await create_intent(
        amount_usd=movie.price_usd,
        order_id=order_id,
        tracking={
            "kind": "single",
            "test": True,
            "user_id": str(test_user.id),
            "content_id": str(movie.id),
        },
        order_details={
            "items": [
                {
                    "name": movie.title,
                    "price": float(movie.price_usd),
                }
            ]
        },
        custom_success_url=str(request.url_for("payment_test_page")),
    )

    intent = PaymentIntent(
        intent_id=baray_intent["_id"],
        order_id=order_id,
        user_id=test_user.id,
        kind="single",
        content_id=movie.id,
        amount_usd=movie.price_usd,
        status="pending",
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)

    return {
        "intent_id": intent.intent_id,
        "order_id": intent.order_id,
        "test_user_id": intent.user_id,
        "movie_id": intent.content_id,
        "amount_usd": format_usd(intent.amount_usd),
        "status": intent.status,
        "checkout_url": checkout_url(intent.intent_id),
    }

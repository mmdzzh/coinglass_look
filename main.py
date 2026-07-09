import asyncio
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import UPDATE_MINUTES
from database import init_db
from sync_service import run_scheduled_sync
from api import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _start_scheduler():
    scheduler = BackgroundScheduler()
    # Register a separate job for each interval so that each interval is
    # refreshed at its own configured cadence (UPDATE_MINUTES).
    for interval, minutes in UPDATE_MINUTES.items():
        if interval in ("1w", "1M"):
            continue
        scheduler.add_job(
            run_scheduled_sync,
            trigger=IntervalTrigger(minutes=minutes),
            id=f"oi_sync_{interval}",
            replace_existing=True,
            coalesce=True,
            kwargs={"intervals": [interval]},
        )
        logger.info(f"Scheduled incremental sync for {interval} every {minutes} minutes.")
    scheduler.start()
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized.")
    scheduler = _start_scheduler()
    # Run an initial incremental sync in the background so it doesn't block startup
    asyncio.create_task(_async_initial_sync())
    yield
    scheduler.shutdown()


async def _async_initial_sync():
    await asyncio.sleep(2)
    try:
        logger.info("Running initial background sync...")
        await asyncio.to_thread(run_scheduled_sync)
        logger.info("Initial background sync complete.")
    except Exception as exc:
        logger.error(f"Initial sync failed: {exc}")


app = FastAPI(
    title="Crypto Open Interest Dashboard",
    description="Historical and live Open Interest data from Binance, Bybit, and Coinglass.",
    version="1.1.0",
    lifespan=lifespan,
)
app.include_router(router)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

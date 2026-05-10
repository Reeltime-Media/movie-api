import asyncio

from transcode_service.worker import run_worker

if __name__ == "__main__":
    asyncio.run(run_worker())

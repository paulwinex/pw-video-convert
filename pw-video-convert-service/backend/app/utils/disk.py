import asyncio
import shutil


def _disk_usage(path: str = "/"):
    total, used, free = shutil.disk_usage(path)
    return {
        "path": path,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "total_gb": round(total / (1024**3), 2),
        "used_gb": round(used / (1024**3), 2),
        "free_gb": round(free / (1024**3), 2),
        "percent_used": round((used / total * 100) if total else 0, 2),
    }


async def get_disk_usage(path: str = "/"):
    return await asyncio.to_thread(_disk_usage, path)

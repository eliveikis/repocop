from fastapi import APIRouter

from repocop import __version__

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}

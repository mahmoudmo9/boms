from fastapi import APIRouter

from app.modules.system import auth, basedata, settings

router = APIRouter()
router.include_router(auth.router)
router.include_router(settings.router)
router.include_router(basedata.router)

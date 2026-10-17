"""Authentication and User Account endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import create_access_token, get_current_user
from config.logging import get_logger
from config.settings import settings
from data.user_repo import UserRepository, verify_password

log = get_logger("api.routes.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=4, description="Password")


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, description="Valid email address")
    password: str = Field(..., min_length=6, description="Password (min 6 characters)")
    full_name: str = Field(default="", description="Full name")


class TradingAccountRequest(BaseModel):
    mt5_login: int = Field(..., description="Exness MT5 account number")
    mt5_password: str = Field(
        default="", description="MT5 trading password (leave empty to keep existing)"
    )
    mt5_server: str = Field(default="Exness-MT5Trial7", description="Exness server name")
    risk_lot_mode: str = Field(default="fixed", description="Lot mode: fixed, compound, or auto")
    lot_size: float = Field(default=0.01, ge=0.01, le=50.0, description="Trading lot size")
    is_active: bool = Field(default=True, description="Enable automatic trading for this account")


@router.post("/register")
async def register(req: RegisterRequest) -> dict[str, Any]:
    repo = UserRepository()
    existing = await repo.get_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered. Please log in.",
        )

    count = await repo.count_users()
    role = "admin" if count == 0 else "user"

    user = await repo.create_user(
        email=req.email,
        password=req.password,
        full_name=req.full_name,
        role=role,
    )

    token = create_access_token(user_id=str(user["id"]), email=user["email"], role=role)
    log.info("new user registered: %s (role: %s)", req.email, role)
    return {
        "status": "ok",
        "token": token,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "full_name": user.get("full_name", ""),
            "role": user["role"],
        },
    }


@router.post("/login")
async def login(req: LoginRequest) -> dict[str, Any]:
    repo = UserRepository()
    user = await repo.get_by_email(req.email)

    # Auto-seed initial admin if database is completely fresh
    if not user:
        count = await repo.count_users()
        initial_token_match = req.password == settings.api_token or (
            bool(settings.mt5_password) and req.password == settings.mt5_password
        )
        if count == 0 and (initial_token_match or len(req.password) >= 8):
            log.info("auto-seeding initial master user: %s", req.email)
            user = await repo.create_user(
                email=req.email,
                password=req.password,
                full_name="Administrator",
                role="admin",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended or inactive",
        )

    token = create_access_token(
        user_id=str(user["id"]),
        email=user["email"],
        role=user.get("role", "user"),
    )

    # Check if trading account configured
    trading_acc = await repo.get_trading_account(user["id"])
    acc_summary = None
    if trading_acc:
        acc_summary = {
            "mt5_login": trading_acc["mt5_login"],
            "mt5_server": trading_acc["mt5_server"],
            "risk_lot_mode": trading_acc["risk_lot_mode"],
            "lot_size": trading_acc["lot_size"],
            "is_active": trading_acc["is_active"],
        }

    return {
        "status": "ok",
        "token": token,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "full_name": user.get("full_name", ""),
            "role": user.get("role", "user"),
            "trading_account": acc_summary,
        },
    }


@router.get("/me")
async def get_me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    repo = UserRepository()
    trading_acc = None
    if current_user.get("id") != "master-admin":
        trading_acc = await repo.get_trading_account(current_user["id"])

    return {
        "user": {
            "id": str(current_user["id"]),
            "email": current_user["email"],
            "full_name": current_user.get("full_name", ""),
            "role": current_user.get("role", "user"),
        },
        "trading_account": (
            {
                "mt5_login": trading_acc["mt5_login"],
                "mt5_server": trading_acc["mt5_server"],
                "risk_lot_mode": trading_acc["risk_lot_mode"],
                "lot_size": trading_acc["lot_size"],
                "is_active": trading_acc["is_active"],
                "updated_at": (
                    trading_acc["updated_at"].isoformat()
                    if trading_acc.get("updated_at")
                    else None
                ),
            }
            if trading_acc
            else None
        ),
    }


@router.post("/trading-account")
async def save_trading_account(
    req: TradingAccountRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.get("id") == "master-admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Master operator uses environment variables for trading account",
        )

    repo = UserRepository()
    existing = await repo.get_trading_account(current_user["id"])
    if not existing and not req.mt5_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MT5 trading password is required for new trading account",
        )

    acc = await repo.upsert_trading_account(
        user_id=current_user["id"],
        mt5_login=req.mt5_login,
        mt5_password=req.mt5_password,
        mt5_server=req.mt5_server,
        risk_lot_mode=req.risk_lot_mode,
        lot_size=req.lot_size,
        is_active=req.is_active,
    )

    log.info("user %s updated MT5 account %s", current_user["email"], req.mt5_login)
    return {
        "status": "ok",
        "trading_account": {
            "mt5_login": acc["mt5_login"],
            "mt5_server": acc["mt5_server"],
            "risk_lot_mode": acc["risk_lot_mode"],
            "lot_size": acc["lot_size"],
            "is_active": acc["is_active"],
            "updated_at": acc["updated_at"].isoformat() if acc.get("updated_at") else None,
        },
    }

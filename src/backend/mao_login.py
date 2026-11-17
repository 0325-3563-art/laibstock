from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

# Temporary hardcoded users
valid_users = {
    "mao_admin": "secure123",
    "mao_staff": "Mao@2026"
}

@router.post("/api/mao-login")
def mao_login(request: LoginRequest):
    if request.username in valid_users and valid_users[request.username] == request.password:
        return {"success": True}
    raise HTTPException(status_code=401, detail="Invalid credentials")

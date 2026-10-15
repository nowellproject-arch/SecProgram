import json
import os
import traceback
from urllib.parse import urlparse, unquote

from dotenv import load_dotenv
from fastapi import APIRouter, Form, File, UploadFile, HTTPException
import pg8000.native

from crb_tables import create_tables, save_payload

load_dotenv()
router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL")

REQUIRED_STORES = ["CongInfo", "GROUPS", "PUBLISHERS", "MonthlyRecords", "RECORDS"]


def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL configuration missing.")
    u = urlparse(DATABASE_URL)
    return pg8000.native.Connection(
        user=unquote(u.username or ""),
        password=unquote(u.password or ""),
        host=u.hostname or "",
        port=u.port or 5432,
        database=u.path.lstrip("/"),
        ssl_context=True          # local PostgreSQL without SSL? change to None (copy only)
    )


@router.post("/import-crb")
async def import_crb_file(
    username: str = Form(...),
    passcode: str = Form(...),
    congregation: str = Form(...),
    file: UploadFile | None = File(None)
):
    conn = None
    clean_passcode = passcode.strip()
    clean_username = username.strip()
    clean_congregation = congregation.strip()

    try:
        conn = get_db_connection()
        create_tables(conn)

        # 1. passcode must be new
        if conn.run("SELECT passcode FROM conginfo WHERE passcode = :p", p=clean_passcode):
            raise HTTPException(status_code=409,
                                detail="This code already exists. Please use Login.")

        # 2. read the CRB file (or make a blank database)
        if file is not None:
            content = await file.read()
            try:
                try:
                    text = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = content.decode("cp1252")
                payload_data = json.loads(text, strict=False)
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"CRB JSON error at line {e.lineno}, column {e.colno}: {e.msg}")

            if not isinstance(payload_data, dict):
                raise HTTPException(status_code=400, detail="Invalid CRB file format.")
            for store in REQUIRED_STORES:
                if store not in payload_data:
                    payload_data[store] = []
        else:
            payload_data = {s: [] for s in REQUIRED_STORES}

        # 3. the form is the truth for passcode / user / congregation
        cong = payload_data.get("CongInfo")
        if not isinstance(cong, list) or not cong or not isinstance(cong[0], dict):
            payload_data["CongInfo"] = [{}]
        payload_data["CongInfo"][0].update({
            "passcode": clean_passcode,
            "user": clean_username,
            "Congregation": clean_congregation,
        })

        # 4. save everything in one transaction (all or nothing)
        conn.run("START TRANSACTION")
        try:
            save_payload(conn, clean_passcode, payload_data)
            conn.run("COMMIT")
        except ValueError as e:
            conn.run("ROLLBACK")
            raise HTTPException(status_code=400, detail=f"Invalid data: {e}")
        except Exception:
            conn.run("ROLLBACK")
            raise

        # 5. same response as before, the browser needs no change
        return {
            "status": "success",
            "action": "created",
            "message": "New account created successfully.",
            "data": payload_data
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()
"""
Roster routes — POST /rosters
                GET  /rosters
                GET  /rosters/{id}
                POST /rosters/{id}/entries
                DELETE /rosters/{id}
"""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from backend.db.database import (
    add_roster_entries,
    create_roster,
    delete_roster,
    get_db,
    get_roster,
    get_roster_entries,
    get_rosters,
)
from backend.services.roster_parser import parse_roster

router = APIRouter()


class RosterCreate(BaseModel):
    name: str


@router.post("/rosters")
def create_roster_endpoint(body: RosterCreate, request: Request):
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        roster_id = create_roster(conn, body.name)
        roster = get_roster(conn, roster_id)
        return dict(roster)
    finally:
        conn.close()


@router.get("/rosters")
def list_rosters_endpoint(request: Request):
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        return get_rosters(conn)
    finally:
        conn.close()


@router.get("/rosters/{roster_id}")
def get_roster_endpoint(roster_id: str, request: Request):
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        roster = get_roster(conn, roster_id)
        if roster is None:
            raise HTTPException(status_code=404, detail=f"Roster {roster_id!r} not found")
        entries = get_roster_entries(conn, roster_id)
        return {**dict(roster), "entries": entries}
    finally:
        conn.close()


@router.post("/rosters/{roster_id}/entries")
async def upload_roster_entries(
    roster_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        roster = get_roster(conn, roster_id)
        if roster is None:
            raise HTTPException(status_code=404, detail=f"Roster {roster_id!r} not found")

        data = await file.read()
        filename = file.filename or "roster.csv"

        try:
            entries = parse_roster(data, filename=filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        entry_dicts = [
            {
                "first_name": e.first_name,
                "last_name": e.last_name,
                "preferred_name": e.preferred_name,
                "student_id": e.student_id,
                "email": e.email,
            }
            for e in entries
        ]
        add_roster_entries(conn, roster_id, entry_dicts)
        return {"roster_id": roster_id, "count": len(entries)}
    finally:
        conn.close()


@router.delete("/rosters/{roster_id}", status_code=204)
def delete_roster_endpoint(roster_id: str, request: Request):
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        roster = get_roster(conn, roster_id)
        if roster is None:
            raise HTTPException(status_code=404, detail=f"Roster {roster_id!r} not found")
        delete_roster(conn, roster_id)
        return Response(status_code=204)
    finally:
        conn.close()

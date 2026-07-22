"""Mock VSP ID card PDF generation."""

from typing import Optional

from google.adk.tools import ToolContext
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from app.config import GENERATED_DIR
from app.tools.members import _load_members

VSP_BLUE = HexColor("#3B5BFF")
INK = HexColor("#1A1A1A")
MUTED = HexColor("#666666")

CARD_WIDTH = 3.5 * inch
CARD_HEIGHT = 2.25 * inch


def _find_dependent(member: dict, dependent_name: str) -> Optional[dict]:
    for dep in member.get("dependents", []):
        if dependent_name.lower() in dep["name"].lower():
            return dep
    return None


def generate_id_card_pdf_impl(member_id: str, dependent_name: Optional[str] = None) -> dict:
    members = _load_members()
    if member_id not in members:
        return {"error": f"Unknown member_id: {member_id}"}
    member = members[member_id]

    holder = member["name"]
    id_number = member["vsp_member_number"]

    if dependent_name:
        dep = _find_dependent(member, dependent_name)
        if dep is None:
            return {"error": f"No dependent named '{dependent_name}' on this plan"}
        holder = dep["name"]
        id_number = dep["vsp_member_number"]

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    safe_holder = holder.replace(" ", "_")
    file_path = GENERATED_DIR / f"vsp_id_card_{member_id}_{safe_holder}.pdf"

    c = canvas.Canvas(str(file_path), pagesize=(CARD_WIDTH, CARD_HEIGHT))

    c.setFillColor(VSP_BLUE)
    c.rect(0, CARD_HEIGHT - 0.4 * inch, CARD_WIDTH, 0.4 * inch, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.15 * inch, CARD_HEIGHT - 0.28 * inch, "VSP Vision Care")

    y = CARD_HEIGHT - 0.65 * inch
    line_height = 0.19 * inch

    def line(label: str, value: str) -> None:
        nonlocal y
        c.setFillColor(INK)
        c.setFont("Helvetica", 7)
        c.drawString(0.15 * inch, y, label)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(1.3 * inch, y, str(value))
        y -= line_height

    line("Member name", holder)
    line("Member ID", id_number)
    line("Plan", member["plan"])
    line("Effective date", member["effective_date"])
    line("Exam / Materials copay", f"${member['copays']['exam']} / ${member['copays']['materials']}")

    c.setFont("Helvetica-Oblique", 6)
    c.setFillColor(MUTED)
    c.drawString(0.15 * inch, 0.12 * inch, "Hackathon mock. Not for clinical use.")

    c.showPage()
    c.save()

    return {
        "file_path": str(file_path),
        "id_number": id_number,
        "holder": holder,
        "plan": member["plan"],
    }


def generate_id_card_pdf(tool_context: ToolContext, dependent_name: Optional[str] = None) -> dict:
    """Generate a downloadable mock VSP ID card PDF for the current member.

    Args:
        dependent_name: if the member is asking for a dependent's ID
            (e.g. their child's), pass the dependent's name -- a
            case-insensitive substring match. Leave unset for the member's
            own card.
    """
    member_id = tool_context.state.get("member_id")
    if not member_id:
        return {"error": "no member_id bound to this session"}
    result = generate_id_card_pdf_impl(member_id, dependent_name)

    # AgentTool (app/agents/id_card_agent.py wraps this specialist) runs the
    # specialist in its own isolated nested Runner and only merges its final
    # *text* back up to the supervisor -- this tool's return dict (with
    # file_path) never reaches the supervisor's own event stream, so the
    # Streamlit UI can't find it there to render a download button. Writing
    # it to session state instead works because AgentTool explicitly
    # forwards every nested event's state_delta up into the parent's
    # ToolContext.state, regardless of nesting depth. "temp:" keeps it
    # scoped to this turn rather than lingering in later turns.
    if "file_path" in result:
        tool_context.state["temp:pdf_path"] = result["file_path"]

    return result

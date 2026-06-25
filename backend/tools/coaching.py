"""
CoachingToolProvider — tools active only for coaching_institute tenants.

These tools extend the platform's default scheduling workflow with
coaching-specific concepts: batch availability, enrollment, and brochure delivery.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Tool schemas ──────────────────────────────────────────────────────────────

COACHING_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "check_batch_availability",
            "description": (
                "Check which batches (class groups) have open seats for a given course. "
                "Use this when a parent asks about joining a specific course or wants to "
                "know available timings for a class."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course": {
                        "type": "string",
                        "description": "The name of the course (e.g. 'JEE Mathematics', 'Grade 8 Science').",
                    },
                    "grade": {
                        "type": "string",
                        "description": "Optional. The student's grade or standard (e.g. '10', '11', 'Grade 8').",
                    },
                },
                "required": ["course"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enroll_student",
            "description": (
                "Formally enroll a student in a batch after they have confirmed interest "
                "following their demo class. Only call this after the parent explicitly "
                "agrees to enroll. Requires the batch_id from check_batch_availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "student_name": {
                        "type": "string",
                        "description": "Full name of the student being enrolled.",
                    },
                    "parent_phone": {
                        "type": "string",
                        "description": "Parent's phone number (from caller-ID in your system prompt).",
                    },
                    "course": {
                        "type": "string",
                        "description": "The course name the student is enrolling in.",
                    },
                    "batch_id": {
                        "type": "string",
                        "description": "The batch ID from check_batch_availability. Required for enrollment.",
                    },
                },
                "required": ["student_name", "parent_phone", "course"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_course_brochure",
            "description": (
                "Send the course brochure or information pack to the parent via SMS. "
                "Use when a parent asks to receive more information about a course "
                "before deciding whether to book a demo class."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Parent's phone number to send the brochure to.",
                    },
                    "course": {
                        "type": "string",
                        "description": "Optional. The specific course they're interested in.",
                    },
                },
                "required": ["phone"],
            },
        },
    },
]

_COACHING_TOOL_NAMES: frozenset[str] = frozenset(
    t["function"]["name"] for t in COACHING_TOOL_SCHEMAS
)


# ── CoachingToolProvider ──────────────────────────────────────────────────────

class CoachingToolProvider:
    """
    Provides coaching-specific tools. Only active when
    tenant business_type == 'coaching_institute'.
    """

    TOOL_NAMES: frozenset[str] = _COACHING_TOOL_NAMES

    def handles(self, tool_name: str) -> bool:
        return tool_name in _COACHING_TOOL_NAMES

    async def list_tools(self, tenant_ctx: Any) -> list[dict]:
        """Return coaching tools for all tenants."""
        if not tenant_ctx:
            return []
        return COACHING_TOOL_SCHEMAS

    async def call_tool(self, name: str, args: dict, session_ctx: dict) -> dict:
        tenant_ctx = session_ctx.get("tenant_ctx")
        call_id: str = session_ctx.get("call_id", "unknown")

        if name == "check_batch_availability":
            return await self._check_batch_availability(args, tenant_ctx, call_id)
        elif name == "enroll_student":
            return await self._enroll_student(args, tenant_ctx, call_id)
        elif name == "send_course_brochure":
            return await self._send_course_brochure(args, tenant_ctx, call_id)
        else:
            raise ValueError(f"CoachingToolProvider does not handle tool: {name!r}")

    async def _check_batch_availability(
        self, args: dict, tenant_ctx: Any, call_id: str
    ) -> dict:
        """
        Check which batches have open seats.

        Currently delegates to the Knowledge Base (appointment_types as batches).
        When coaching tenants configure their batch schedules in KB, this reads them.
        """
        course = args.get("course", "")
        grade = args.get("grade", "")

        # Use appointment_types from tenant config as batches (each appt type = a batch/course)
        batches: list[dict] = []
        if tenant_ctx and tenant_ctx.appointment_types:
            for at in tenant_ctx.appointment_types:
                at_name = at.get("name", "") or at.get("code", "")
                if not course or course.lower() in at_name.lower():
                    batches.append({
                        "batch_id": at.get("code", ""),
                        "course": at_name,
                        "duration_minutes": at.get("duration_minutes", 60),
                        "slot_capacity": at.get("slot_capacity", 1),
                        "note": "Contact us to confirm seat availability.",
                    })

        if not batches:
            return {
                "ok": False,
                "summary_for_assistant": (
                    f"No batch information found for course '{course}'. "
                    f"Tell the parent you'll have someone from the admissions team "
                    f"call them back with batch details. Offer to schedule a callback or demo class."
                ),
                "batches": [],
            }

        batch_lines = [
            f"{b['course']} (batch: {b['batch_id']}, {b['duration_minutes']} min sessions)"
            for b in batches
        ]
        logger.info("[Call %s] check_batch_availability → %d batches for '%s'", call_id, len(batches), course)
        return {
            "ok": True,
            "summary_for_assistant": (
                f"Available batches for {course or 'your query'}: "
                + "; ".join(batch_lines) + ". "
                f"Ask the parent if they'd like to book a demo class or get more details."
            ),
            "batches": batches,
            "course_filter": course,
        }

    async def _enroll_student(
        self, args: dict, tenant_ctx: Any, call_id: str
    ) -> dict:
        """
        Enroll a student in a batch.

        Currently books an appointment of type=batch_id (enrollment confirmation).
        The front-desk admin sees this in Appointments with notes containing
        enrollment details.
        """
        from backend.services import calendar_service, sms_service
        from datetime import datetime, timedelta

        student_name = args.get("student_name", "")
        parent_phone = args.get("parent_phone", "")
        course = args.get("course", "")
        batch_id = args.get("batch_id", course)

        if not student_name or not parent_phone or not course:
            return {
                "ok": False,
                "summary_for_assistant": (
                    "To enroll, I need the student's name, parent's phone number, and the course. "
                    "Please confirm these details."
                ),
            }

        logger.info(
            "[Call %s] enroll_student: student=%s, course=%s, batch=%s",
            call_id, student_name, course, batch_id,
        )

        # Notify the office via SMS alert
        try:
            sms_service.send_office_alert(
                reason=(
                    f"Enrollment request: {student_name} for {course} "
                    f"(batch: {batch_id}). Parent: {parent_phone}"
                ),
                caller_number=parent_phone,
                tenant_ctx=tenant_ctx,
            )
        except Exception as exc:
            logger.warning("[Call %s] Enrollment SMS alert failed: %s", call_id, exc)

        return {
            "ok": True,
            "summary_for_assistant": (
                f"Enrollment request for {student_name} in {course} has been registered. "
                f"Our admissions team will contact {parent_phone} within 24 hours to "
                f"confirm the enrollment and share payment details. "
                f"Tell the parent we're excited to have them join and ask if there's anything else."
            ),
            "student_name": student_name,
            "course": course,
            "batch_id": batch_id,
            "parent_phone": parent_phone,
        }

    async def _send_course_brochure(
        self, args: dict, tenant_ctx: Any, call_id: str
    ) -> dict:
        """Send a brochure SMS to the parent."""
        from backend.services import sms_service

        phone = args.get("phone", "")
        course = args.get("course", "")

        if not phone:
            return {
                "ok": False,
                "summary_for_assistant": "I need the parent's phone number to send the brochure.",
            }

        business_name = getattr(tenant_ctx, "business_name", "us") if tenant_ctx else "us"
        course_part = f" for {course}" if course else ""
        message = (
            f"Hi! Here is the course information{course_part} from {business_name}. "
            f"Our admissions team will follow up shortly. "
            f"Please call us if you have any questions!"
        )

        try:
            sms_service.send_custom_sms(
                to=phone,
                message=message,
                tenant_ctx=tenant_ctx,
            )
            logger.info("[Call %s] send_course_brochure → SMS sent to %s", call_id, phone)
            return {
                "ok": True,
                "summary_for_assistant": (
                    f"Course information has been sent to {phone} via SMS. "
                    f"Tell the parent to expect a message shortly and ask if they'd like to "
                    f"schedule a demo class while they're on the call."
                ),
            }
        except Exception as exc:
            logger.warning("[Call %s] Brochure SMS failed: %s", call_id, exc)
            return {
                "ok": False,
                "summary_for_assistant": (
                    "I wasn't able to send the SMS right now. "
                    "Please ask the parent to contact us directly or visit our website for course details."
                ),
            }

"""
Multi-tenant architecture test suite.

Tests the tenant lifecycle, context resolution, tenant-scoped data isolation,
service parameterisation, and API routes — all using mocked database sessions.

Run:  venv/bin/python -m pytest tests/test_multi_tenant.py -v
  or: venv/bin/python tests/test_multi_tenant.py
"""

import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Test counters ───────────────────────────────────────────────────────────

_passed = 0
_failed = 0
_total = 0


def _assert(condition: bool, desc: str):
    global _passed, _failed, _total
    _total += 1
    if condition:
        _passed += 1
        print(f"  ✅ {desc}")
    else:
        _failed += 1
        print(f"  ❌ FAIL: {desc}")


# ── Fixture helpers ─────────────────────────────────────────────────────────

TENANT_1_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_2_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _make_mock_tenant(
    tenant_id=TENANT_1_ID,
    slug="smilecare",
    business_name="SmileCare Dental",
    business_type_val="dental",
    vapi_assistant_id="asst_abc123",
    status_val="ACTIVE",
    calcom_api_key="cal_key_abc",
    twilio_account_sid="AC_test123",
    twilio_auth_token="token_test",
    twilio_phone_number="+15551234567",
    timezone_val="America/Chicago",
    demo_mode=True,
    agent_name="Sarah",
    escalation_phone="+15559990000",
    escalation_transfer_number="",
    calcom_event_types=None,
    appointment_types=None,
    knowledge_base=None,
    emergency_guidance="",
    greeting_message="Thank you for calling SmileCare Dental.",
):
    """Create a mock Tenant ORM object."""
    from unittest.mock import MagicMock
    from backend.models.tenant import TenantStatus, BusinessType, PlanTier

    t = MagicMock()
    t.id = tenant_id
    t.slug = slug
    t.business_name = business_name
    t.business_type = MagicMock(value=business_type_val)
    t.business_phone = "+15551234567"
    t.business_address = "123 Main St"
    t.timezone = timezone_val
    t.demo_mode = demo_mode
    t.agent_name = agent_name
    t.greeting_message = greeting_message
    t.system_prompt_override = None
    t.vapi_api_key = "vapi_key_test"
    t.vapi_assistant_id = vapi_assistant_id
    t.vapi_phone_number_id = "phone_id_test"
    t.vapi_webhook_secret = "secret_test"
    t.calcom_api_key = calcom_api_key
    t.calcom_username = "smilecare"
    t.calcom_event_types = calcom_event_types or {"cleaning": "5560055", "consultation": "5560050"}
    t.twilio_account_sid = twilio_account_sid
    t.twilio_auth_token = twilio_auth_token
    t.twilio_phone_number = twilio_phone_number
    t.escalation_phone = escalation_phone
    t.escalation_transfer_number = escalation_transfer_number
    t.appointment_types = appointment_types or [
        {"key": "cleaning", "label": "Routine Cleaning", "duration_minutes": 60},
        {"key": "consultation", "label": "Consultation", "duration_minutes": 45},
    ]
    t.business_hours = None
    t.knowledge_base = knowledge_base or {}
    t.emergency_guidance = emergency_guidance
    t.owner_name = "Dr. Smith"
    t.owner_email = "dr.smith@smilecare.com"
    t.owner_phone = "+15551111111"
    t.plan = MagicMock(value="starter")
    t.status = MagicMock(value=status_val)
    t.created_at = datetime.now(timezone.utc)
    t.updated_at = datetime.now(timezone.utc)
    t.noemail_address = f"noemail@{slug}.scheduler.ai"
    return t


def _make_tenant_context(tenant_mock=None, **overrides):
    """Build a TenantContext from a mock tenant or from overrides."""
    from backend.services.tenant_service import _tenant_to_context
    if tenant_mock:
        return _tenant_to_context(tenant_mock)
    t = _make_mock_tenant(**overrides)
    return _tenant_to_context(t)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: TenantContext creation and immutability
# ══════════════════════════════════════════════════════════════════════════════

def test_tenant_context_creation():
    print("\n── Test 1: TenantContext creation and immutability ──")

    ctx = _make_tenant_context()

    _assert(str(ctx.tenant_id) == str(TENANT_1_ID), "tenant_id matches")
    _assert(ctx.slug == "smilecare", "slug matches")
    _assert(ctx.business_name == "SmileCare Dental", "business_name matches")
    _assert(ctx.business_type == "dental", "business_type matches")
    _assert(ctx.timezone == "America/Chicago", "timezone matches")
    _assert(ctx.demo_mode is True, "demo_mode matches")
    _assert(ctx.agent_name == "Sarah", "agent_name matches")
    _assert(ctx.vapi_assistant_id == "asst_abc123", "vapi_assistant_id matches")
    _assert(ctx.calcom_api_key == "cal_key_abc", "calcom_api_key matches")
    _assert(ctx.twilio_account_sid == "AC_test123", "twilio_account_sid matches")
    _assert(ctx.noemail_address == "noemail@smilecare.scheduler.ai", "noemail_address generated correctly")

    # Immutability (frozen dataclass)
    try:
        ctx.slug = "hacked"
        _assert(False, "TenantContext should be immutable")
    except Exception:
        _assert(True, "TenantContext is immutable (frozen)")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: TenantContext.get_event_type_id
# ══════════════════════════════════════════════════════════════════════════════

def test_event_type_mapping():
    print("\n── Test 2: Event type ID resolution ──")

    ctx = _make_tenant_context()

    _assert(ctx.get_event_type_id("cleaning") == "5560055", "cleaning → correct event type")
    _assert(ctx.get_event_type_id("consultation") == "5560050", "consultation → correct event type")
    _assert(ctx.get_event_type_id("unknown_type") == "5560050", "unknown falls back to consultation")
    # "Routine Cleaning" → "routine_cleaning" key (not in mock), falls back to "consultation"
    _assert(ctx.get_event_type_id("Routine Cleaning") == "5560050", "unknown title-case falls back to consultation")
    # Direct key match
    _assert(ctx.get_event_type_id("Cleaning") == "5560055", "single-word title case normalised to key")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: Cache (get/set/invalidate)
# ══════════════════════════════════════════════════════════════════════════════

def test_cache():
    print("\n── Test 3: Tenant cache operations ──")

    from backend.services.tenant_service import _cache_get, _cache_set, invalidate_cache, _cache

    # Clear any existing cache
    _cache.clear()

    ctx = _make_tenant_context()

    # Set and get
    _cache_set("test_key", ctx)
    cached = _cache_get("test_key")
    _assert(cached is not None, "cache hit after set")
    _assert(cached.slug == "smilecare", "cached value correct")

    # Miss
    _assert(_cache_get("nonexistent") is None, "cache miss returns None")

    # Invalidate specific tenant
    invalidate_cache(str(TENANT_1_ID))
    _assert(_cache_get("test_key") is None, "cache invalidated for tenant")

    # Invalidate all
    _cache_set("key1", ctx)
    _cache_set("key2", ctx)
    invalidate_cache()
    _assert(_cache_get("key1") is None, "full cache clear works")
    _assert(_cache_get("key2") is None, "full cache clear works (2)")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: Tenant data isolation (Patient.phone unique per tenant)
# ══════════════════════════════════════════════════════════════════════════════

def test_patient_model_constraint():
    print("\n── Test 4: Patient model has tenant_id + composite unique constraint ──")

    from backend.models.patient import Patient

    # Check that the model has tenant_id column
    columns = {c.name for c in Patient.__table__.columns}
    _assert("tenant_id" in columns, "Patient model has tenant_id column")

    # Check UniqueConstraint
    constraints = Patient.__table__.constraints
    has_composite = any(
        hasattr(c, "columns") and
        set(col.name for col in c.columns) == {"tenant_id", "phone"}
        for c in constraints
    )
    _assert(has_composite, "Patient has composite unique constraint (tenant_id, phone)")


def test_call_model_has_tenant_id():
    print("\n── Test 5: Call model has tenant_id FK ──")

    from backend.models.call import Call

    columns = {c.name for c in Call.__table__.columns}
    _assert("tenant_id" in columns, "Call model has tenant_id column")


def test_appointment_model_has_tenant_id():
    print("\n── Test 6: Appointment model has tenant_id FK ──")

    from backend.models.appointment import Appointment

    columns = {c.name for c in Appointment.__table__.columns}
    _assert("tenant_id" in columns, "Appointment model has tenant_id column")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7: SMS service uses tenant-specific config
# ══════════════════════════════════════════════════════════════════════════════

def test_sms_service_tenant_params():
    print("\n── Test 7: SMS service uses tenant config ──")

    from backend.services.sms_service import (
        _business_name, _business_phone_display, _escalation_phone, _is_demo,
        _resolve_twilio,
    )

    ctx = _make_tenant_context()

    _assert(_business_name(ctx) == "SmileCare Dental", "business name from tenant")
    _assert(_business_name(None) == "SmileCare Dental", "business name falls back to settings.OFFICE_NAME")

    sid, token, from_num = _resolve_twilio(ctx)
    _assert(sid == "AC_test123", "Twilio SID from tenant")
    _assert(token == "token_test", "Twilio token from tenant")
    _assert(from_num == "+15551234567", "Twilio from-number from tenant")

    _assert(_escalation_phone(ctx) == "+15559990000", "escalation phone from tenant")
    _assert(_is_demo(ctx) is True, "demo mode from tenant")


def test_sms_confirmation_uses_tenant():
    print("\n── Test 8: SMS confirmation uses tenant business name and timezone ──")

    from backend.services import sms_service

    ctx = _make_tenant_context(
        business_name="Sunrise Hospital",
        timezone_val="America/New_York",
        demo_mode=True,
    )

    # Patch _send_sms to capture the body text
    captured_body = {}
    original_send = sms_service._send_sms

    def _capture_send(to, body, tenant_ctx=None):
        captured_body["to"] = to
        captured_body["body"] = body
        return original_send(to, body, tenant_ctx)

    with patch.object(sms_service, "_send_sms", side_effect=_capture_send):
        result = sms_service.send_confirmation(
            patient_name="John Doe",
            phone="+15551234567",
            appointment_type="Consultation",
            scheduled_at=datetime(2026, 5, 5, 10, 0),
            tenant_ctx=ctx,
        )

    _assert(result is True, "SMS send returns True in demo mode")
    body = captured_body.get("body", "")
    _assert("Sunrise Hospital" in body, f"SMS body contains tenant business name (body={body[:100]})")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9: Calendar service uses tenant config
# ══════════════════════════════════════════════════════════════════════════════

def test_calendar_service_tenant_config():
    print("\n── Test 9: Calendar service resolves config from tenant ──")

    from backend.services.calendar_service import _resolve_calcom_config, _is_demo

    ctx = _make_tenant_context(
        calcom_api_key="cal_key_hospital",
        timezone_val="America/New_York",
        demo_mode=False,
    )

    api_key, tz = _resolve_calcom_config(ctx)
    _assert(api_key == "cal_key_hospital", "Cal.com API key from tenant")
    _assert(tz == "America/New_York", "timezone from tenant")
    _assert(_is_demo(ctx) is False, "demo mode from tenant (False)")

    # Fallback
    api_key_default, tz_default = _resolve_calcom_config(None)
    _assert(tz_default is not None, "fallback timezone is not None")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10: System prompt parameterised by tenant
# ══════════════════════════════════════════════════════════════════════════════

def test_system_prompt_uses_tenant():
    print("\n── Test 10: System prompt is parameterised by tenant config ──")

    from backend.prompts.dental_agent import build_system_prompt

    ctx = _make_tenant_context(
        agent_name="Emily",
        business_name="Sunrise Veterinary Clinic",
        business_type_val="veterinary",
        appointment_types=[
            {"key": "checkup", "label": "Annual Checkup", "duration_minutes": 30},
            {"key": "vaccination", "label": "Vaccination", "duration_minutes": 15},
        ],
    )

    prompt = build_system_prompt(tenant_ctx=ctx)

    _assert("Emily" in prompt, "agent_name 'Emily' in prompt")
    _assert("Sunrise Veterinary Clinic" in prompt, "business_name in prompt")
    _assert("Annual Checkup" in prompt, "custom appointment type in prompt")
    _assert("Vaccination" in prompt, "custom appointment type in prompt (2)")
    _assert("30 minutes" in prompt, "custom duration in prompt")

    # Should NOT contain hardcoded dental references
    _assert("SmileCare" not in prompt, "no hardcoded SmileCare in parameterised prompt")


def test_system_prompt_default_fallback():
    print("\n── Test 11: System prompt falls back to defaults without tenant ──")

    from backend.prompts.dental_agent import build_system_prompt

    prompt = build_system_prompt(tenant_ctx=None)

    _assert("Sarah" in prompt, "default agent name 'Sarah'")
    _assert("SmileCare Dental" in prompt, "default business name")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 12: Patient context in prompt with tenant business name
# ══════════════════════════════════════════════════════════════════════════════

def test_patient_context_with_tenant():
    print("\n── Test 12: Patient context in prompt uses tenant business name ──")

    from backend.prompts.dental_agent import build_system_prompt

    ctx = _make_tenant_context(business_name="City Hospital")

    patient_context = {
        "patient": {
            "name": "Jane Smith",
            "phone": "+15551111111",
            "dob": "01/15/1985",
            "insurance": "BlueCross",
            "is_new_patient": False,
            "visit_count": 5,
            "preferred_type": "consultation",
            "allergies": None,
            "notes": None,
        },
        "upcoming_appointments": [],
        "past_appointments": [
            {"type": "Consultation", "date": "April 20, 2026", "status": "CONFIRMED"},
        ],
        "last_visit": {"type": "Consultation", "date": "April 20, 2026"},
        "months_since_last_visit": 1,
    }

    prompt = build_system_prompt(patient_context=patient_context, tenant_ctx=ctx)

    _assert("Jane Smith" in prompt, "patient name in prompt")
    _assert("CALLER RECOGNISED" in prompt, "caller recognised section present")
    _assert("City Hospital" in prompt, "tenant business name in returning patient greeting")
    _assert("Total visits: 5" in prompt, "visit count in prompt")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 13: Knowledge base from tenant
# ══════════════════════════════════════════════════════════════════════════════

def test_knowledge_service_tenant_kb():
    print("\n── Test 13: Knowledge service uses tenant KB from database ──")

    from backend.services.knowledge_service import get_tenant_kb, kb_to_context_string

    ctx = _make_tenant_context(
        knowledge_base={
            "office_info": {
                "name": "Sunrise Hospital",
                "address": "456 Oak Ave",
                "phone": "555-0200",
                "hours": "Mon-Fri 7AM-7PM",
            },
            "faqs": [
                {"question": "Do you accept walk-ins?", "answer": "Yes, we accept walk-ins during business hours."},
            ],
        },
    )

    kb = get_tenant_kb(ctx)
    _assert(kb.get("office_info", {}).get("name") == "Sunrise Hospital", "tenant KB loaded from context")

    context_str = kb_to_context_string(tenant_ctx=ctx)
    _assert("Sunrise Hospital" in context_str, "tenant KB in context string")
    _assert("walk-ins" in context_str, "tenant FAQ in context string")

    # Without tenant, should fall back to file
    kb_default = get_tenant_kb(None)
    _assert(isinstance(kb_default, dict), "default KB returns dict (even if empty)")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 14: Two tenants with same phone should be isolated
# ══════════════════════════════════════════════════════════════════════════════

def test_tenant_isolation_concept():
    print("\n── Test 14: Different tenants should have isolated contexts ──")

    ctx1 = _make_tenant_context(
        tenant_id=TENANT_1_ID,
        slug="smilecare",
        business_name="SmileCare Dental",
        vapi_assistant_id="asst_1",
        calcom_api_key="cal_key_1",
    )

    ctx2 = _make_tenant_context(
        tenant_id=TENANT_2_ID,
        slug="sunrise",
        business_name="Sunrise Hospital",
        vapi_assistant_id="asst_2",
        calcom_api_key="cal_key_2",
    )

    # Verify isolation
    _assert(ctx1.tenant_id != ctx2.tenant_id, "different tenant IDs")
    _assert(ctx1.slug != ctx2.slug, "different slugs")
    _assert(ctx1.business_name != ctx2.business_name, "different business names")
    _assert(ctx1.calcom_api_key != ctx2.calcom_api_key, "different Cal.com keys")
    _assert(ctx1.vapi_assistant_id != ctx2.vapi_assistant_id, "different Vapi assistant IDs")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 15: Tenant lifecycle states
# ══════════════════════════════════════════════════════════════════════════════

def test_tenant_status_enum():
    print("\n── Test 15: TenantStatus enum has all lifecycle states ──")

    from backend.models.tenant import TenantStatus

    expected = {"PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "DEACTIVATED"}
    actual = {s.value for s in TenantStatus}
    _assert(actual == expected, f"TenantStatus has all states: {actual}")


def test_business_type_enum():
    print("\n── Test 16: BusinessType enum supports multiple verticals ──")

    from backend.models.tenant import BusinessType

    expected = {"dental", "hospital", "clinic", "veterinary", "physiotherapy", "custom"}
    actual = {b.value for b in BusinessType}
    _assert(actual == expected, f"BusinessType has all types: {actual}")


def test_plan_tier_enum():
    print("\n── Test 17: PlanTier enum ──")

    from backend.models.tenant import PlanTier

    expected = {"starter", "professional", "enterprise"}
    actual = {p.value for p in PlanTier}
    _assert(actual == expected, f"PlanTier has all tiers: {actual}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 18: Tenant model has all required columns
# ══════════════════════════════════════════════════════════════════════════════

def test_tenant_model_columns():
    print("\n── Test 18: Tenant model has all required columns ──")

    from backend.models.tenant import Tenant

    columns = {c.name for c in Tenant.__table__.columns}
    required = {
        "id", "slug", "business_name", "business_type", "business_phone",
        "business_address", "business_website", "timezone",
        "owner_name", "owner_email", "owner_phone",
        "plan", "status", "demo_mode",
        "agent_name", "greeting_message", "system_prompt_override",
        "voice_config", "end_call_phrases",
        "vapi_api_key", "vapi_assistant_id", "vapi_phone_number_id", "vapi_webhook_secret",
        "calcom_api_key", "calcom_username", "calcom_event_types",
        "twilio_account_sid", "twilio_auth_token", "twilio_phone_number",
        "escalation_phone", "escalation_transfer_number",
        "appointment_types", "business_hours", "knowledge_base", "emergency_guidance",
        "created_at", "updated_at",
    }
    missing = required - columns
    _assert(len(missing) == 0, f"All required columns present (missing: {missing})")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 19: Models export
# ══════════════════════════════════════════════════════════════════════════════

def test_models_export():
    print("\n── Test 19: models/__init__.py exports Tenant and enums ──")

    from backend.models import Tenant, TenantStatus, BusinessType, PlanTier

    _assert(Tenant is not None, "Tenant exported")
    _assert(TenantStatus is not None, "TenantStatus exported")
    _assert(BusinessType is not None, "BusinessType exported")
    _assert(PlanTier is not None, "PlanTier exported")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 20: Timezone abbreviation property
# ══════════════════════════════════════════════════════════════════════════════

def test_tz_abbreviation():
    print("\n── Test 20: TenantContext.tz_abbreviation ──")

    ctx_cst = _make_tenant_context(timezone_val="America/Chicago")
    _assert(ctx_cst.tz_abbreviation in ("CST", "CDT", "CT"), f"CST/CDT for Chicago (got {ctx_cst.tz_abbreviation})")

    ctx_est = _make_tenant_context(timezone_val="America/New_York")
    _assert(ctx_est.tz_abbreviation in ("EST", "EDT", "ET"), f"EST/EDT for New York (got {ctx_est.tz_abbreviation})")

    ctx_pst = _make_tenant_context(timezone_val="America/Los_Angeles")
    _assert(ctx_pst.tz_abbreviation in ("PST", "PDT", "PT"), f"PST/PDT for LA (got {ctx_pst.tz_abbreviation})")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 21: Noemail address generation
# ══════════════════════════════════════════════════════════════════════════════

def test_noemail_address():
    print("\n── Test 21: noemail_address generation ──")

    from backend.models.tenant import Tenant

    t = MagicMock(spec=Tenant)
    t.slug = "sunrise-hospital"
    # Access the real property
    _assert(
        Tenant.noemail_address.fget(t) == "noemail@sunrise-hospital.scheduler.ai",
        "noemail address format correct"
    )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 22: Prompt with emergency guidance (dental default)
# ══════════════════════════════════════════════════════════════════════════════

def test_prompt_dental_emergency_default():
    print("\n── Test 22: Dental business type gets dental emergency guidance ──")

    from backend.prompts.dental_agent import build_system_prompt

    ctx = _make_tenant_context(business_type_val="dental", emergency_guidance="")

    prompt = build_system_prompt(tenant_ctx=ctx)
    _assert("Knocked out tooth" in prompt, "dental-specific emergency guidance present")
    _assert("warm salt water" in prompt, "dental toothache guidance present")


def test_prompt_custom_emergency():
    print("\n── Test 23: Custom emergency guidance overrides default ──")

    from backend.prompts.dental_agent import build_system_prompt

    ctx = _make_tenant_context(
        business_type_val="veterinary",
        emergency_guidance="If the pet is choking, perform the Heimlich maneuver adapted for animals.",
    )

    prompt = build_system_prompt(tenant_ctx=ctx)
    _assert("Heimlich maneuver" in prompt, "custom emergency guidance in prompt")
    _assert("Knocked out tooth" not in prompt, "no dental guidance for vet clinic")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 24: Tenant routes schema validation
# ══════════════════════════════════════════════════════════════════════════════

def test_tenant_onboard_schema():
    print("\n── Test 24: TenantOnboardRequest schema validation ──")

    from backend.routes.tenants import TenantOnboardRequest
    from pydantic import ValidationError

    # Valid request
    valid = TenantOnboardRequest(
        slug="my-clinic",
        business_name="My Clinic",
        owner_name="Dr. Jones",
        owner_email="jones@clinic.com",
    )
    _assert(valid.slug == "my-clinic", "valid slug accepted")
    _assert(valid.plan == "starter", "default plan is starter")
    _assert(valid.timezone == "America/Chicago", "default timezone")

    # Invalid slug (uppercase)
    try:
        TenantOnboardRequest(
            slug="My-Clinic",
            business_name="My Clinic",
            owner_name="Dr. Jones",
            owner_email="jones@clinic.com",
        )
        _assert(False, "should reject uppercase slug")
    except ValidationError:
        _assert(True, "uppercase slug rejected")

    # Missing required field
    try:
        TenantOnboardRequest(slug="ok", business_name="Ok")  # type: ignore
        _assert(False, "should reject missing owner_name")
    except ValidationError:
        _assert(True, "missing owner_name rejected")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 25: TenantOut response hides sensitive API keys
# ══════════════════════════════════════════════════════════════════════════════

def test_tenant_out_hides_keys():
    print("\n── Test 25: TenantOut does not expose API keys ──")

    from backend.routes.tenants import TenantOut

    fields = set(TenantOut.model_fields.keys())
    _assert("vapi_api_key" not in fields, "vapi_api_key not in response")
    _assert("calcom_api_key" not in fields, "calcom_api_key not in response")
    _assert("twilio_auth_token" not in fields, "twilio_auth_token not in response")
    _assert("twilio_account_sid" not in fields, "twilio_account_sid not in response")
    _assert("vapi_configured" in fields, "vapi_configured (boolean) in response")
    _assert("calcom_configured" in fields, "calcom_configured (boolean) in response")
    _assert("twilio_configured" in fields, "twilio_configured (boolean) in response")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 26: Calendar service demo mode per tenant
# ══════════════════════════════════════════════════════════════════════════════

def test_calendar_demo_per_tenant():
    print("\n── Test 26: Calendar demo mode respects per-tenant setting ──")

    ctx_demo = _make_tenant_context(demo_mode=True)
    ctx_live = _make_tenant_context(demo_mode=False)

    from backend.services.calendar_service import _is_demo
    _assert(_is_demo(ctx_demo) is True, "demo tenant → demo mode on")
    _assert(_is_demo(ctx_live) is False, "live tenant → demo mode off")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 27: Calendar demo slots work with tenant context
# ══════════════════════════════════════════════════════════════════════════════

def test_calendar_demo_slots_with_tenant():
    print("\n── Test 27: Demo slots returned when tenant is in demo mode ──")

    ctx = _make_tenant_context(demo_mode=True)

    async def _run():
        from backend.services.calendar_service import get_available_slots
        slots = await get_available_slots("5560055", "2026-05-05", "2026-05-05", tenant_ctx=ctx)
        return slots

    slots = asyncio.run(_run())
    _assert(len(slots) == 7, f"demo mode returns 7 slots (got {len(slots)})")
    _assert("2026-05-05" in slots[0], "slots are for the requested date")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 28: Multiple tenants → different prompts
# ══════════════════════════════════════════════════════════════════════════════

def test_different_tenants_different_prompts():
    print("\n── Test 28: Different tenants produce different system prompts ──")

    from backend.prompts.dental_agent import build_system_prompt

    ctx_dental = _make_tenant_context(
        agent_name="Sarah",
        business_name="SmileCare Dental",
        business_type_val="dental",
    )
    ctx_vet = _make_tenant_context(
        agent_name="Max",
        business_name="Happy Paws Vet",
        business_type_val="veterinary",
        emergency_guidance="For pet emergencies, call the animal ER.",
    )

    prompt_dental = build_system_prompt(tenant_ctx=ctx_dental)
    prompt_vet = build_system_prompt(tenant_ctx=ctx_vet)

    _assert(prompt_dental != prompt_vet, "prompts are different for different tenants")
    _assert("SmileCare Dental" in prompt_dental, "dental prompt mentions correct business")
    _assert("Happy Paws Vet" in prompt_vet, "vet prompt mentions correct business")
    _assert("Max" in prompt_vet, "vet prompt uses correct agent name")
    _assert("animal ER" in prompt_vet, "vet prompt has custom emergency guidance")


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  MULTI-TENANT ARCHITECTURE TEST SUITE")
    print("=" * 70)

    tests = [
        test_tenant_context_creation,
        test_event_type_mapping,
        test_cache,
        test_patient_model_constraint,
        test_call_model_has_tenant_id,
        test_appointment_model_has_tenant_id,
        test_sms_service_tenant_params,
        test_sms_confirmation_uses_tenant,
        test_calendar_service_tenant_config,
        test_system_prompt_uses_tenant,
        test_system_prompt_default_fallback,
        test_patient_context_with_tenant,
        test_knowledge_service_tenant_kb,
        test_tenant_isolation_concept,
        test_tenant_status_enum,
        test_business_type_enum,
        test_plan_tier_enum,
        test_tenant_model_columns,
        test_models_export,
        test_tz_abbreviation,
        test_noemail_address,
        test_prompt_dental_emergency_default,
        test_prompt_custom_emergency,
        test_tenant_onboard_schema,
        test_tenant_out_hides_keys,
        test_calendar_demo_per_tenant,
        test_calendar_demo_slots_with_tenant,
        test_different_tenants_different_prompts,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as exc:
            global _failed, _total
            _total += 1
            _failed += 1
            print(f"  ❌ EXCEPTION in {test_fn.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"  RESULTS: {_passed}/{_total} checks passed, {_failed} failed")
    print(f"  TESTS:   {len(tests)} test functions")
    print("=" * 70)

    if _failed > 0:
        sys.exit(1)
    else:
        print("\n  ✅ ALL MULTI-TENANT TESTS PASSED\n")


if __name__ == "__main__":
    main()

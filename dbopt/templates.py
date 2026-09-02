"""Builders for the text of deletion / opt-out requests.

Nothing here sends anything. Each function returns (subject, body) strings that
the user reviews and then sends from their own mail client, or pastes into the
broker's web form.
"""
from __future__ import annotations

from .models import Profile, Settings


def _identity_block(p: Profile) -> str:
    cur = p.current_address()
    lines = [
        f"  Full name: {p.full_name}",
    ]
    if p.aliases:
        lines.append(f"  Also known as: {', '.join(p.aliases)}")
    if cur:
        lines.append(f"  Current address: {cur.one_line()}")
    priors = p.prior_addresses()
    if priors:
        lines.append("  Prior addresses:")
        lines.extend(f"    - {a.one_line()}" for a in priors)
    if p.emails:
        lines.append(f"  Email address(es): {', '.join(p.emails)}")
    if p.phones:
        lines.append(f"  Telephone number(s): {', '.join(p.phones)}")
    if p.birth_year:
        lines.append(f"  Year of birth: {p.birth_year}")
    return "\n".join(lines)


def _listing_block(listing_urls: list[str]) -> str:
    if not listing_urls:
        return ""
    urls = "\n".join(f"    - {u}" for u in listing_urls)
    return (
        "\nThe following pages / records on your service correspond to this "
        "individual and must be removed:\n" + urls + "\n"
    )


def _signature(s: Settings, p: Profile) -> str:
    name = s["signature_name"] or p.full_name
    reply = s["reply_to_email"] or (p.emails[0] if p.emails else "")
    agent = " (authorized agent for the individual named above)" if s["is_authorized_agent"] and s["signature_name"] else ""
    out = name + agent
    if reply:
        out += f"\nReply to: {reply}"
    return out


def build_ccpa(p: Profile, broker: dict, s: Settings, listing_urls: list[str]) -> tuple[str, str]:
    subject = "CCPA/CPRA Request to Delete and Opt Out of Sale/Sharing of Personal Information"
    body = f"""To the Privacy Officer, {broker['name']}:

I submit this request under the California Consumer Privacy Act (Cal. Civ. Code
Sec. 1798.100 et seq.), as amended by the California Privacy Rights Act.

I request that {broker['name']}, together with its subsidiaries, affiliates and
data-supplier partners:

  1. DELETE all personal information you have collected about the individual
     identified below (Cal. Civ. Code Sec. 1798.105);
  2. Stop selling and sharing that personal information and treat this as a
     request to opt out under Cal. Civ. Code Sec. 1798.120;
  3. Direct any service providers or third parties to do the same; and
  4. Confirm in writing when this is complete and state the categories of
     personal information that were deleted.

Individual this request is about:
{_identity_block(p)}
{_listing_block(listing_urls)}
Please treat this message as a verifiable consumer request. If you must verify
identity, use the email address this was sent from; do not require me to create
an account or provide more data than is necessary to locate the records.

Please respond within 45 days as required by Cal. Civ. Code Sec. 1798.130. If you
believe you are exempt (e.g. FCRA-regulated data), identify the specific data and
exemption and delete everything not covered.

Regards,
{_signature(s, p)}
"""
    return subject, body


def build_gdpr(p: Profile, broker: dict, s: Settings, listing_urls: list[str]) -> tuple[str, str]:
    subject = "GDPR Article 17 Erasure Request and Article 21 Objection"
    body = f"""To the Data Protection Officer, {broker['name']}:

I invoke my rights under the EU General Data Protection Regulation (and the UK
GDPR where applicable).

  1. Under Article 17, erase all personal data you hold about the individual
     identified below.
  2. Under Article 21, I object to any processing of that data for direct
     marketing or for your legitimate-interests profiling; cease it immediately.
  3. Under Article 19, notify each recipient to whom the data was disclosed.
  4. Under Article 15, tell me what data you held and its sources.

Individual this request is about:
{_identity_block(p)}
{_listing_block(listing_urls)}
Please act without undue delay and within one month (Article 12(3)). If you
refuse, state your reasons and my right to complain to a supervisory authority.

Regards,
{_signature(s, p)}
"""
    return subject, body


def build_us_generic(p: Profile, broker: dict, s: Settings, listing_urls: list[str]) -> tuple[str, str]:
    subject = "Request to Delete Personal Information and Opt Out of Its Sale"
    body = f"""To the Privacy Officer, {broker['name']}:

I am exercising my consumer privacy rights under the applicable state law of my
residence (which may include the CCPA/CPRA in California, the VCDPA in Virginia,
the CPA in Colorado, the CTDPA in Connecticut, the UCPA in Utah, or a comparable
statute). Regardless of state, I request that you:

  1. Delete all personal information you hold about the individual identified
     below and instruct your sources and downstream recipients to do the same;
  2. Stop selling, sharing or licensing that information and register this as an
     opt-out of targeted advertising and profiling;
  3. Suppress the individual from future data acquisitions; and
  4. Confirm completion in writing.

Individual this request is about:
{_identity_block(p)}
{_listing_block(listing_urls)}
Please confirm receipt and respond within 45 days. Do not require account
creation. If any data is exempt under the FCRA or GLBA, identify it specifically
and delete the remainder.

Regards,
{_signature(s, p)}
"""
    return subject, body


_BUILDERS = {
    "CCPA": build_ccpa,
    "GDPR": build_gdpr,
    "US-STATE-GENERIC": build_us_generic,
}


def build(law_basis: str, p: Profile, broker: dict, s: Settings, listing_urls: list[str] | None = None):
    fn = _BUILDERS.get(law_basis, build_us_generic)
    return fn(p, broker, s, listing_urls or [])

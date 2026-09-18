"""The dialogue manager.

This walks QuestionNode rows in the database. There is no hardcoded question
sequence anywhere in this application. Adding a new chief complaint with its
own follow-up branch is an INSERT, not a deploy — see /clinician/ontology.
"""
from models import QuestionNode

SECTION_LABELS = {
    "chief_complaint": "Chief complaint",
    "hpi": "History of present illness",
    "past": "Past medical and surgical history",
    "drug_allergy": "Drug and allergy history",
    "family": "Family history",
    "personal": "Personal history",
    "ros": "Review of systems",
    "dashavidha": "Dashavidha Pariksha",
}

# The order intake flows in. Dashavidha only runs in ayush mode.
SECTION_ORDER = ["chief_complaint", "hpi", "ros", "past", "drug_allergy",
                 "family", "personal", "dashavidha"]


def localized_prompt(node, lang):
    return (getattr(node, f"prompt_{lang}", None) or node.prompt_en)


def localized_options(node, lang):
    out = []
    for opt in (node.options or []):
        label = opt.get(f"label_{lang}") or opt.get("label_en") or opt.get("value")
        out.append({"value": opt.get("value"), "label": label,
                    "label_en": opt.get("label_en", ""), "icon": opt.get("icon")})
    return out


def _visible(node, answers, complaint, mode):
    if not node.active:
        return False
    if node.practitioner_only:
        return False
    if node.section == "dashavidha" and mode != "ayush":
        return False
    if node.complaint_tag and node.complaint_tag != complaint:
        return False
    if node.parent_node:
        parent = answers.get(node.parent_node)
        if not parent:
            return False
        val = parent.get("value")
        wanted = node.show_if_value
        if wanted is None:
            return True
        if isinstance(val, list):
            return wanted in val
        return str(val) == str(wanted)
    return True


def build_plan(answers, complaint, mode="ayush"):
    """Every node that should be asked, in order, given what we know so far."""
    nodes = QuestionNode.query.filter_by(active=True).order_by(
        QuestionNode.order_index).all()
    by_section = {s: [] for s in SECTION_ORDER}
    for node in nodes:
        if node.section not in by_section:
            continue
        if _visible(node, answers, complaint, mode):
            by_section[node.section].append(node)
    plan = []
    for section in SECTION_ORDER:
        plan.extend(by_section[section])
    return plan


def next_node(answers, complaint, mode="ayush"):
    """The next unanswered node, plus progress numbers for the rail."""
    plan = build_plan(answers, complaint, mode)
    answered = sum(1 for n in plan if n.node_id in answers)
    for node in plan:
        if node.node_id not in answers:
            return node, answered, len(plan)
    return None, answered, len(plan)


def practitioner_nodes():
    return QuestionNode.query.filter_by(practitioner_only=True, active=True)\
        .order_by(QuestionNode.order_index).all()


def label_for(node, value):
    """Turn a stored value back into human text for the case sheet."""
    if value is None:
        return ""
    opts = {o.get("value"): o.get("label_en") or o.get("value")
            for o in (node.options or [])}
    if isinstance(value, list):
        return ", ".join(opts.get(v, str(v)) for v in value)
    return opts.get(value, str(value))


def structured_history(case):
    """Group confirmed answers by clinical section for display and export."""
    answers = case.answers or {}
    nodes = {n.node_id: n for n in QuestionNode.query.all()}
    grouped = {}
    for node_id, entry in answers.items():
        node = nodes.get(node_id)
        if not node:
            continue
        section = node.section
        grouped.setdefault(section, []).append({
            "node_id": node_id,
            "prompt": node.prompt_en,
            "value": entry.get("value"),
            "label": entry.get("label") or label_for(node, entry.get("value")),
            "source": entry.get("source", "touch"),
            "confidence": entry.get("confidence", 1.0),
            "raw": entry.get("raw", ""),
            "socrates_slot": node.socrates_slot,
            "dashavidha_param": node.dashavidha_param,
            "order": node.order_index,
        })
    for items in grouped.values():
        items.sort(key=lambda x: x["order"])
    return grouped

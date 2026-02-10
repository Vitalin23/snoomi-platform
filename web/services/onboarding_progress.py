import json

from flask import has_request_context, url_for
from flask_login import current_user


def _safe_json_dict(raw_value):
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_nonempty_topics(raw_topics):
    if not raw_topics:
        return False
    if isinstance(raw_topics, str):
        stripped = raw_topics.strip()
        if not stripped:
            return False
        try:
            raw_topics = json.loads(stripped)
        except Exception:
            return bool(stripped)

    if isinstance(raw_topics, list):
        for item in raw_topics:
            if isinstance(item, str) and item.strip():
                return True
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("topic") or "").strip()
                if title:
                    return True
        return False

    if isinstance(raw_topics, dict):
        return _has_nonempty_topics(raw_topics.get("topics") or [])

    return False


def build_onboarding_progress(
    *,
    client_channel_model,
    channel_topic_model,
    channel_setting_model,
    channel_post_model,
    is_admin_user,
):
    default_payload = {"show": False}
    if not has_request_context() or not current_user.is_authenticated:
        return default_payload
    if is_admin_user(current_user) or not current_user.client_id:
        return default_payload

    channels = (
        client_channel_model.query.filter_by(client_id=current_user.client_id, is_active=True)
        .order_by(client_channel_model.created_at.desc())
        .all()
    )
    channel_ids = [channel.id for channel in channels]

    step1_done = bool(channel_ids)
    step2_done = False
    step3_done = False

    if channel_ids:
        step2_done = (
            channel_topic_model.query.filter(
                channel_topic_model.channel_id.in_(channel_ids),
                channel_topic_model.is_active.is_(True),
            )
            .limit(1)
            .first()
            is not None
        )

        if not step2_done:
            settings_rows = (
                channel_setting_model.query.filter(channel_setting_model.channel_id.in_(channel_ids))
                .with_entities(channel_setting_model.topics)
                .all()
            )
            for (topics_value,) in settings_rows:
                if _has_nonempty_topics(topics_value):
                    step2_done = True
                    break

        for channel in channels:
            extra = _safe_json_dict(channel.additional_config)
            topic_plan = extra.get("topic_plan") if isinstance(extra.get("topic_plan"), dict) else {}
            if not step2_done and _has_nonempty_topics(topic_plan.get("topics") or []):
                step2_done = True

            posting_draft = (
                extra.get("posting_plan_draft")
                if isinstance(extra.get("posting_plan_draft"), dict)
                else {}
            )
            plan_items = posting_draft.get("plan_items") if isinstance(posting_draft, dict) else []
            if isinstance(plan_items, list):
                has_draft_items = any(
                    isinstance(item, dict)
                    and str(item.get("topic") or "").strip()
                    and str(item.get("publish_date") or "").strip()
                    for item in plan_items
                )
                if has_draft_items:
                    step3_done = True

            if step2_done and step3_done:
                break

    step4_done = (
        channel_post_model.query.join(
            client_channel_model, channel_post_model.channel_id == client_channel_model.id
        )
        .filter(client_channel_model.client_id == current_user.client_id)
        .filter(channel_post_model.success.is_(True))
        .limit(1)
        .first()
        is not None
    )

    steps = [
        {
            "key": "channels",
            "title": "Шаг 1",
            "label": "Подключение канала",
            "description": "Проверьте и сохраните хотя бы один канал",
            "url": url_for("channels"),
            "done": step1_done,
        },
        {
            "key": "topics",
            "title": "Шаг 2",
            "label": "План тем",
            "description": "Сгенерируйте и сохраните темы",
            "url": url_for("posting_setup"),
            "done": step2_done,
        },
        {
            "key": "calendar",
            "title": "Шаг 3",
            "label": "Календарь",
            "description": "Соберите и сохраните черновик расписания",
            "url": url_for("posting_plan"),
            "done": step3_done,
        },
        {
            "key": "publish",
            "title": "Шаг 4",
            "label": "Старт публикации",
            "description": "Сделайте первый ручной запуск публикации",
            "url": f"{url_for('dashboard')}#publishNowTopic",
            "done": step4_done,
        },
    ]

    completed_steps = 0
    for step in steps:
        if step["done"]:
            completed_steps += 1
        else:
            break

    first_incomplete_idx = next((idx for idx, step in enumerate(steps) if not step["done"]), None)
    for idx, step in enumerate(steps):
        step["is_current"] = first_incomplete_idx == idx

    progress_percent = int(round((completed_steps / len(steps)) * 100))
    next_step = steps[first_incomplete_idx] if first_incomplete_idx is not None else None

    return {
        "show": True,
        "steps": steps,
        "completed_steps": completed_steps,
        "total_steps": len(steps),
        "progress_percent": progress_percent,
        "channels_count": len(channels),
        "next_step": next_step,
    }


import asyncio
from typing import Any, Text, Dict, List
import json
from rasa_sdk import Action
from rasa_sdk.events import FollowupAction, SlotSet
from .celery_app import trigger_intent, celery, get_db_all, get_db_row
from .utils.rate_limiter import GlobalRateLimiter
from .utils.llm_caller import get_llm_response
import datetime
import requests
import string
import os
import math
from dateutil import tz
from pytz import timezone
import time
import urllib
import re

rate_limiter = GlobalRateLimiter()

def get_next_item(item2find, list2search):
    if len(list2search) > 0:
        found = 0
        for item in list2search:
            if found == 1:
                return item
            if str(item) == str(item2find):
                found = 1

        if str(item2find) == str(list2search[-1]):
            return None

        return list2search[0]
    return None


def get_slots(sender_id):
    tmp_query = get_db_all(
        "select * from events_slots where sender_id = %s", [sender_id]
    )

    slots = {}

    if tmp_query is not None:
        for _slot in tmp_query:
            slots[_slot["key2find"]] = _slot["value"]

    return slots


def set_slot(sender_id, key2find, value2set):
    tmp_query = get_db_row(
        "select id from events_slots where sender_id = %s and key2find = %s",
        [sender_id, key2find],
    )
    if tmp_query is None:
        get_db_row(
            "INSERT INTO `events_slots` (`sender_id`, `key2find`) VALUES (%s, %s)",
            [sender_id, key2find],
        )
    tmp_query2 = get_db_row(
        "update events_slots set value = %s where sender_id = %s and key2find = %s",
        [value2set, sender_id, key2find],
    )
    return tmp_query2


def reset_all_slots(sender_id):
    get_db_row("delete from events_slots where sender_id = %s", [sender_id])
    return True


def get_countdown_by_length(string):
    return math.ceil(len(string) / 150) * 3


def units2seconds(unit, count):
    unit2second = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}

    try:
        return int(unit2second[unit] * int(math.ceil(float(count))))
    except:
        return int(1)


def validate_answer_rules(text2match, latest_message):
    base_latest_message = latest_message.strip().lower()
    base_text2match = text2match.strip().lower()
    return (
        base_latest_message == base_text2match or base_text2match in base_latest_message
    )


def date_seconds_diff(date2diff):
    now = datetime.datetime.now(tz.gettz("Europe/Prague"))
    try:
        if now.timestamp() > date2diff.timestamp():
            return int(1)
        return int(date2diff.timestamp() - now.timestamp())
    except:
        return int(1)


def translate_text(translate_key):
    # removed translations module
    return translate_key


def get_active_tasks(sender_id):
    i = celery.control.inspect()
    _tasks = []

    for queue in i.scheduled():
        for _task in i.scheduled()[queue]:
            if (
                _task
                and _task.get("kwargs")
                and _task.get("kwargs").get("sender_id") == sender_id
                and _task not in _tasks
            ):
                _tasks.append(_task)

    for queue in i.active():
        for _task in i.active()[queue]:
            if (
                _task
                and _task.get("kwargs")
                and _task.get("kwargs").get("sender_id") == sender_id
                and _task not in _tasks
            ):
                _tasks.append(_task)

    for queue in i.reserved():
        for _task in i.reserved()[queue]:
            if (
                _task
                and _task.get("kwargs")
                and _task.get("kwargs").get("sender_id") == sender_id
                and _task not in _tasks
            ):
                _tasks.append(_task)
    return _tasks


def get_active_tasks_alt(sender_id):
    _tasks = get_db_all(
        "select task_id from planned_tasks where sender_id = %s and is_finished = 0",
        [sender_id],
    )
    tasks = []
    for _task in _tasks:
        tasks.append(_task["task_id"])
    return tasks


def reset_all_tasks(sender_id):
    tasks = get_active_tasks_alt(sender_id)
    for task_id in tasks:
        celery.control.revoke(task_id, terminate=True)
        get_db_row(
            "update planned_tasks set is_finished = 1 where task_id = %s", [task_id]
        )


def trigger_intent_quiz(sender_id, countdown):
    tmp_task_id = trigger_intent.apply_async(
        args=[{"sender_id": sender_id}], countdown=countdown
    )
    target_eta = datetime.datetime.now() + datetime.timedelta(0, countdown)
    target_datetime = target_eta.strftime("%Y-%m-%d %H:%M:%S")
    get_db_row(
        "INSERT INTO `planned_tasks` (`sender_id`, `task_id`, `eta`) VALUES (%s, %s, %s)",
        [sender_id, tmp_task_id, target_datetime],
    )
    return


def sec_to_hhmmss(seconds):
    _a = str(seconds // 3600)
    _b = str((seconds % 3600) // 60)
    _c = str((seconds % 3600) % 60)

    a = _a if len(_a) > 1 else "0" + _a
    b = _b if len(_b) > 1 else "0" + _b
    c = _c if len(_c) > 1 else "0" + _c

    return f"{a}:{b}:{c}"


def get_first_eta(sender_id):
    _planned_task = get_db_row(
        "select eta from planned_tasks where sender_id = %s and is_finished = 0 order by eta desc limit 1",
        [sender_id],
    )

    if _planned_task is not None and _planned_task.get("eta") is not None:
        return sec_to_hhmmss(date_seconds_diff(_planned_task["eta"]))

    return sec_to_hhmmss(1)


def get_first_task_seconds(sender_id):
    _planned_task = get_db_row(
        "select eta from planned_tasks where sender_id = %s and is_finished = 0 order by eta desc limit 1",
        [sender_id],
    )

    if _planned_task is not None and _planned_task.get("eta") is not None:
        return date_seconds_diff(_planned_task["eta"])

    return 1


def fix_text2send(text2send):
    # telegram...
    try:
        if text2send not in [None, ""]:
            return text2send
        else:
            raise Exception()
    except:
        return "."


def trim_to_50(text2send):
    # telegram limit 50 chars
    try:
        return text2send[:50]
    except:
        return ""
    
def get_utterances(events, sender_is_user=True, message_position=0, latest_question=None):
    def format_question_with_buttons(question):
        _options = [
            f"{l}: {option}"
            for l, option in zip(string.ascii_lowercase, question["options"])
        ]
        return f'{question["text"]}\nmožnosti na výběr:\n{" | ".join(_options)}'

    if sender_is_user:
        sender = "user"
    else:
        sender = "bot"

    if latest_question and sender == "bot":
        return format_question_with_buttons(latest_question)
    
    text = ""
    last_message_sender = ""
    found_right_message = False
    messages_found = 0
    
    for e in reversed(events):
        if e["event"] in ["user", "bot"]:
            if e["event"] == sender and (last_message_sender != sender or found_right_message) and e.get("text", "") != "EXTERNAL: EXTERNAL_reminder":
                if message_position != 0 and last_message_sender != sender:
                    message_position -= 1
                    last_message_sender = e["event"]
                    continue

                found_right_message = True
                messages_found += 1
                message = e.get("text", "")
                if sender == "bot":
                    try:
                        if len(e.get("data", {}).get("buttons", [])) > 0:
                            question = {"text": message, "options": []}
                            for btn in e["data"]["buttons"]:
                                option_text = btn.get("title", "") or btn.get("payload", "")
                                question["options"].append(option_text)
                            if question["options"]:
                                message = format_question_with_buttons(question)
                    except:
                        ...
                else:
                    text = str(message) + "\n" + str(text)
            else:
                last_message_sender = e["event"]
            
    return text

def get_formated_chat_history(events, gpt_type=""):
   
    chat_history = []
    
    for e in events:
        if e["event"] in ["user", "bot"]:
            if e.get("text", "") not in ["EXTERNAL: EXTERNAL_reminder", "/get_started"]:
                if e["event"] == "user":
                    text = e.get("text", "")
                    if gpt_type == "1" and len(text) > 300:
                        text = text[:300]
                        
                    chat_history.append({"role": "user", "content": text})
                    if "reset" in text.lower() or "restart" in text.lower():
                        chat_history = []
                else:
                    chat_history.append({"role": "assistant", "content": e.get("text", "")})
    
    return chat_history

class ActionQuiz(Action):
    def name(self) -> Text:
        return "action_quiz"

    async def run(self, dispatcher, tracker, domain):
        timer = time.time()
        latest_message = tracker.latest_message.get("text", "")
        sender_id = tracker.current_state()["sender_id"]

        slots = get_slots(sender_id)

        if latest_message == "/get_started" and slots.get("gpt_conversation", ""):
            if slots.get("conversation_started") == "1":
                return [FollowupAction("action_listen")]
            set_slot(sender_id, "conversation_started", "1")
        

        current_step = slots.get("current_step", "")
        lecture_id = slots.get("current_lecture", "")
        current_lecture = lecture_id
        current_course = slots.get("current_course", "")
        being_asked = slots.get("being_asked", "")
        resetted = slots.get("resetted")
        command = slots.get("command", "")
        _delayed_answers = slots.get("delayed_answers", "")
        gpt_conversation = slots.get("gpt_conversation", "")

        delayed_answers = (
            json.loads(_delayed_answers) if _delayed_answers not in [None, ""] else []
        )

        latest_message2check = slots.get("latest_message2check", "")
        number_tries = slots.get("number_tries", "")

        events = tracker.current_state()["events"]
        latest_bot_event = {}
        for e in tracker.events:
            if e["event"] == "bot" and e["text"] != "":
                latest_bot_event = e["text"]
                break
        user_events = []
        for e in events:
            if e["event"] == "user" and e["text"] != "EXTERNAL: EXTERNAL_reminder":
                user_events.append(e)

        custom_course = None
        try:
            if user_events[-1]["metadata"]["custom_course"]:
                custom_course = user_events[-1]["metadata"]["custom_course"]
        except:
            ...

        if latest_message.lower() in ["reset", "restart"] and not resetted:
            dispatcher.utter_message(text=translate_text("Resetováno"))
            reset_all_slots(sender_id)
            reset_all_tasks(sender_id)
            trigger_intent_quiz(sender_id, 1)
            return [FollowupAction("action_quiz")]
        
        if latest_message.lower() == "/use_gemma":
            dispatcher.utter_message(
                text="Příkaz /use_gemma byl zrušen. Použijte model s prefixem openai/ nebo groq/."
            )
            return [FollowupAction("action_listen")]

        # asking mff
        if "/w" in latest_message.lower() and len(latest_message) > 2 and command == "":
            message2send = latest_message.split("/w")[1]
            set_slot(sender_id, "command", "1")
            try:
                mffcuni = requests.post(
                    os.environ.get("MFF_URL"),
                    json={
                        "q": message2send,
                        "exact": 1,
                        "w": 1,
                        "last": latest_bot_event,
                        "site": tracker.get_latest_input_channel(),
                        "course": 0,
                        "user_id": sender_id,
                    },
                )

                mff_text = mffcuni.json().get("a", "")
                if len(mff_text) > 0:
                    dispatcher.utter_message(text=mff_text)
                trigger_intent_quiz(sender_id, 1)
                return [FollowupAction("action_listen")]
            except Exception as e:
                print(e)
                dispatcher.utter_message(
                    text=f"Omlouvám se, část mozku mi právě nefunguje."
                )

        if "/e" in latest_message.lower() and len(latest_message) > 2 and command == "":
            message2send = latest_message.split("/e")[1].strip()
            prompt = "\n".join([
                ""
            ])
            #response = await get_llm_response(message)
            set_slot(sender_id, "command", "1")
            dispatcher.utter_message(
                text=f"https://ema.rvp.cz/vyhledat-material?searchForm-type=wizard&searchForm-filter[search]={urllib.parse.quote(message2send)}"
            )
            trigger_intent_quiz(sender_id, 1)
            return [FollowupAction("action_listen")]  
        
        if gpt_conversation in ["1", "edu", "max"] and latest_message != "/get_started":
            if latest_message.lower().strip() == "/model":
                dispatcher.utter_message(
                    text=f"Používám model: {await rate_limiter.get_model()}"
                )
                return [FollowupAction("action_listen")]
            
            gpt_conversation_counter = slots.get("gpt_conversation_counter", "0")
            if int(gpt_conversation_counter) > 15 and gpt_conversation == "1":
                dispatcher.utter_message(
                    text="Omlouvám se, ale už jsem už jsem toho řekl dost. Jdu spát."
                )  
                return [FollowupAction("action_listen")]
            
            if int(gpt_conversation_counter) > 25 and gpt_conversation in ["edu"]:
                dispatcher.utter_message(
                    text="Omlouvám se, ale už jsem už jsem toho řekl dost. Napište mi kontakt a lidský kolega se vám ozve."
                )
                return [FollowupAction("action_listen")]
            
            if int(gpt_conversation_counter) > 25 and gpt_conversation in ["max"]:
                dispatcher.utter_message(
                    text="Už jsem toho řekl dost. Prosím zvažte napsání: reset nebo restart pro nový začátek."
                )

            sorted_events = sorted(
                events,
                key=lambda d: d["timestamp"],
            )
            initial_prompt = get_db_row(
                "select description from courses where id = %s", [custom_course]
            )

            # Get the history from get_utterances
            history = get_formated_chat_history(sorted_events, gpt_conversation)

            # Ensure initial_prompt["description"] is a string and not None
            description = ""
            if initial_prompt and isinstance(initial_prompt, dict):
                description = initial_prompt.get("description") or ""
            # Remove GPT markers if present
            description = description.replace("##GPT##", "").replace("##GPT_EDU##", "").replace("##GPT_MAX##", "")

            if gpt_conversation == "1":
                system_prompt = "system: Odpovídej stručně (max 100 slov) a jasně. Klidně používej emoji. "
            elif gpt_conversation == "edu":
                system_prompt = "system: Odpovídej stručně (max 250 slov) a jasně. Klidně používej emoji. "
            else:
                system_prompt = ""

            prompt = [
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": description},
            ] + history + [
                {"role": "system", "content": system_prompt}
            ]

            # Filter out any messages with None or empty content
            prompt = [msg for msg in prompt if msg.get("content") not in [None, ""]]

            response = await get_llm_response(chat=prompt)

            # Replace multiple newlines with a single newline
            # response = re.sub(r"\n\s*\n", " \n ", response)
            
            dispatcher.utter_message(text=response)  # default webchat handling of multiple messages is fine

            """
            messages = response.split("\n")
            first = True
            for message in messages:
                if first:
                    first = False
                    continue
                else:
                    ...
                dispatcher.utter_message(text=message)
            """

            set_slot(sender_id, "gpt_conversation_counter", str(int(gpt_conversation_counter) + 1))
            print(f"full timer: {round(time.time() - timer, 4)}", flush=True)
            return [FollowupAction("action_listen")]

        # checking till pause ends
        if (
            len(get_active_tasks_alt(sender_id)) > 0
            and latest_message != "EXTERNAL: EXTERNAL_reminder"
        ):
            if get_first_task_seconds(sender_id) > 120:
                dispatcher.utter_message(
                    text=f"{translate_text('edu.pause_till')} {get_first_eta(sender_id)} s"
                )
            return [FollowupAction("action_quiz")]

        if custom_course and current_course == "":
            set_slot(sender_id, "current_course", custom_course)
            course2run = get_db_row(
                "select name from courses where id = %s", [custom_course]
            )
            if course2run:
                description = get_db_row(
                    "select description from courses where id = %s", [custom_course]
                ).get("description", "")

                if "##GPT##" in description:
                    dispatcher.utter_message("Dobrý den, jak vám mohu pomoci?")
                    set_slot(sender_id, "gpt_conversation", "1")
                    return [FollowupAction("action_listen")]
                elif "##GPT_EDU##" in description:
                    dispatcher.utter_message(
                        "Dobrý den, jak vám mohu pomoci? Neváhejte se zeptat."
                    )
                    set_slot(sender_id, "gpt_conversation", "edu")
                    return [FollowupAction("action_listen")]
                elif "##GPT_MAX##" in description:
                    dispatcher.utter_message(
                        "Dobrý den, jak vám mohu pomoci? Neváhejte se zeptat."
                    )
                    set_slot(sender_id, "gpt_conversation", "max")
                    return [FollowupAction("action_listen")]
                
                dispatcher.utter_message(
                    text=f"Spouštím kurz {course2run.get('name', '')}"
                )

                lecture2go_query = get_db_row(
                    "select id from lectures where course_id = %s order by position limit 1",
                    [custom_course],
                )

                if lecture2go_query:
                    set_slot(sender_id, "current_lecture", str(lecture2go_query["id"]))
                    return [FollowupAction("action_quiz")]
                else:
                    dispatcher.utter_message(
                        text=translate_text("edu.no_lection_in_course")
                    )
                    return [FollowupAction("action_listen")]
        
        set_slot(sender_id, "command", "")

        steps2go_query = get_db_all(
            "select * from lectures_steps where parent_id = 0 and lecture_id = %s order by position",
            [lecture_id],
        )
        steps2go = []
        if steps2go_query:
            for step2go in steps2go_query:
                steps2go.append(step2go["id"])

        lectures2go_query = get_db_all(
            "select * from lectures where course_id = %s order by position",
            [current_course],
        )
        lectures2go = []
        if lectures2go_query:
            for lecture2go in lectures2go_query:
                lectures2go.append(lecture2go["id"])

        if current_lecture == "":
            try:
                lecture_id = lectures2go[0]
            except:
                dispatcher.utter_message(
                    text=translate_text("edu.no_lection_in_course")
                )
                lecture_id = ""

            if lecture_id != "":
                set_slot(sender_id, "current_lecture", str(lecture_id))
                return [FollowupAction("action_quiz")]
            else:
                return [FollowupAction("action_listen")]

        company_id = 0

        if current_step == "":
            current_step = get_next_item(None, steps2go)

        step = get_db_row(
            "select * from lectures_steps where lecture_id = %s and parent_id = 0 and id = %s order by position limit 1",
            [lecture_id, current_step],
        )

        if not step:
            set_slot(sender_id, "current_step", "")
            dispatcher.utter_message(
                text=f"Co dál?", buttons=[{"title": "Reset", "payload": "reset"}]
            )
            return [FollowupAction("action_listen")]

        if step["response_type"] == "information":
            if step["step_type"] == "image":
                dispatcher.utter_message(
                    image=f"{os.getenv('PROJECT_URL', '')}/static/uploads/{step['text']}"
                )
            else:
                dispatcher.utter_message(text=f"{fix_text2send(step['text'])}")

            substeps = get_db_all(
                "select * from lectures_steps where lecture_id = %s and parent_id = %s order by position",
                [lecture_id, step["id"]],
            )
            for substep in substeps:
                if substep["step_type"] == "image":
                    dispatcher.utter_message(
                        image=f"{os.getenv('PROJECT_URL', '')}/static/uploads/{substep['text']}"
                    )
                elif substep["step_type"] in ["link", "video"]:
                    dispatcher.utter_message(text=f"{fix_text2send(substep['text'])}")
                else:
                    dispatcher.utter_message(text=f"{fix_text2send(substep['text'])}")
            if str(steps2go[-1]) == str(step["id"]):
                set_slot(sender_id, "current_step", "")
                set_slot(
                    sender_id, "current_lecture", get_next_item(lecture_id, lectures2go)
                )
            else:
                set_slot(sender_id, "current_step", get_next_item(step["id"], steps2go))
                set_slot(sender_id, "being_asked", "")

            return [FollowupAction("action_quiz")]

        elif step["response_type"] == "question":
            answers = get_db_all(
                "select * from lectures_answers where step_id = %s and parent_id = 0 order by position",
                [step["id"]],
            )
            empty_text2match = next(
                (True for answer in answers if answer["text2match"] == ""), False
            )

            if being_asked == "":
                buttons = []
                for answer in answers:
                    buttons.append(
                        {
                            "title": trim_to_50(answer.get("text", ""))
                            if (answer["text"] != "" and step["free_input"])
                            else trim_to_50(answer.get("text2match", "")),
                            "payload": trim_to_50(answer.get("text2match", ""))
                            if answer["text2match"] != ""
                            else "EMPTYPAYLOAD",
                        }
                    )

                if empty_text2match is True:
                    buttons = []

                set_slot(sender_id, "being_asked", "1")

                if step.get("text3", "") not in [None, ""]:
                    dispatcher.utter_message(text=fix_text2send(step.get("text3", "")))

                if step["text2"] not in [None, ""]:
                    dispatcher.utter_message(
                        image=f"{os.getenv('PROJECT_URL', '')}/static/uploads/{fix_text2send(step['text2'])}"
                    )

                if str(step["free_input"]) != "1":
                    question_button_text = (
                        step["text"]
                        if step["text"] not in [None, ""]
                        else "Vyberte jednu z možností:"
                    )
                    dispatcher.utter_message(
                        text=fix_text2send(question_button_text),
                        buttons=buttons,
                        button_type="vertical",
                    )
                else:
                    dispatcher.utter_message(text=fix_text2send(step.get("text", "")))

                return [
                    SlotSet(
                        "lecture_step",
                        f"{company_id}.{current_course}.{lecture_id}.{step['id']}",
                    ),
                    SlotSet("lecture_question", "1"),
                    FollowupAction("action_listen"),
                ]
            else:
                if str(step["free_input"]) != "1" and empty_text2match is True:
                    latest_message = ""

                if latest_message != "EXTERNAL: EXTERNAL_reminder":
                    set_slot(sender_id, "latest_message2check", latest_message)
                else:
                    latest_message = latest_message2check

                if str(step["free_input"]) != "1":
                    selected_answer = next(
                        (
                            answer
                            for answer in answers
                            if trim_to_50(answer.get("text2match", "")).strip()
                            == latest_message
                        ),
                        None,
                    )
                else:
                    selected_answer = None
                    if str(steps2go[-1]) == str(step["id"]):
                        set_slot(sender_id, "current_step", "")
                        set_slot(
                            sender_id,
                            "current_lecture",
                            get_next_item(lecture_id, lectures2go),
                        )
                    else:
                        set_slot(
                            sender_id,
                            "current_step",
                            get_next_item(step["id"], steps2go),
                        )

                if selected_answer is not None:
                    if selected_answer["id"] not in delayed_answers:
                        delayed_answers.append(selected_answer["id"])
                        set_slot(
                            sender_id,
                            "delayed_answers",
                            json.dumps(delayed_answers),
                        )
                        if selected_answer["answer_type"] == "text":
                            if selected_answer["text2"] not in [None, ""]:
                                dispatcher.utter_message(
                                    text=f"""{fix_text2send(selected_answer["text2"])}"""
                                )
                        elif selected_answer["answer_type"] in ["link", "video"]:
                            if selected_answer["text2"] not in [None, ""]:
                                dispatcher.utter_message(
                                    text=f"""{fix_text2send(selected_answer["text2"])}"""
                                )
                        elif selected_answer["answer_type"] == "image":
                            if selected_answer["text2"] not in [None, ""]:
                                dispatcher.utter_message(
                                    image=f"{os.getenv('PROJECT_URL', '')}/static/uploads/{selected_answer['text2']}"
                                )
                        elif selected_answer["answer_type"] == "pause":
                            if selected_answer["text2"] in [
                                "seconds",
                                "minutes",
                                "hours",
                                "days",
                            ]:
                                trigger_intent_quiz(
                                    sender_id,
                                    units2seconds(
                                        selected_answer["text2"],
                                        selected_answer["description"],
                                    ),
                                )
                                return [FollowupAction("action_listen")]

                    subanswers = get_db_all(
                        "select * from lectures_answers where parent_id = %s and step_id = %s order by position",
                        [selected_answer["id"], step["id"]],
                    )
                    for subanswer in subanswers:
                        if subanswer["id"] not in delayed_answers:
                            delayed_answers.append(subanswer["id"])
                            set_slot(
                                sender_id,
                                "delayed_answers",
                                json.dumps(delayed_answers),
                            )
                            if subanswer["answer_type"] == "text":
                                if subanswer["text2"] not in [None, ""]:
                                    dispatcher.utter_message(
                                        text=f"""{fix_text2send(subanswer["text2"])}"""
                                    )
                            elif subanswer["answer_type"] in ["link", "video"]:
                                if subanswer["text2"] not in [None, ""]:
                                    dispatcher.utter_message(
                                        text=f"""{fix_text2send(subanswer["text2"])}"""
                                    )
                            elif subanswer["answer_type"] == "image":
                                if subanswer["text2"] not in [None, ""]:
                                    dispatcher.utter_message(
                                        image=f"""{os.getenv('PROJECT_URL', '')}/static/uploads/{subanswer["text2"]}"""
                                    )
                            elif subanswer["answer_type"] == "pause":
                                if subanswer["text2"] in [
                                    "seconds",
                                    "minutes",
                                    "hours",
                                    "days",
                                ]:
                                    trigger_intent_quiz(
                                        sender_id,
                                        units2seconds(
                                            subanswer["text2"], subanswer["description"]
                                        ),
                                    )
                                    return [FollowupAction("action_listen")]

                    set_slot(sender_id, "delayed_answers", "")
                    set_slot(sender_id, "being_asked", "")
                    set_slot(sender_id, "latest_message2check", "")
                    set_slot(sender_id, "delayed_selected_answers", "")

                    if selected_answer["following_action"] == "next":
                        if str(steps2go[-1]) == str(step["id"]):
                            set_slot(sender_id, "current_step", "")
                            set_slot(
                                sender_id,
                                "current_lecture",
                                get_next_item(lecture_id, lectures2go),
                            )
                        else:
                            set_slot(
                                sender_id,
                                "current_step",
                                get_next_item(step["id"], steps2go),
                            )
                            ...
                    elif selected_answer["following_action"] == "again":
                        ...
                    elif selected_answer["following_action"] == "lecture":
                        _lecture = get_db_row(
                            "select * from lectures where id = %s order by id limit 1",
                            [selected_answer["following_action_id"]],
                        )
                        if not _lecture:
                            dispatcher.utter_message(
                                text=f"edu.following_lecture_not_found"
                            )
                            return [FollowupAction("action_listen")]

                        set_slot(
                            sender_id,
                            "current_lecture",
                            selected_answer["following_action_id"],
                        )
                        set_slot(sender_id, "current_step", "")
                        set_slot(sender_id, "number_tries", "")

                    elif selected_answer["following_action"] == "course":
                        _course = get_db_row(
                            "select * from courses where id = %s order by id limit 1",
                            [selected_answer["following_action_id"]],
                        )
                        if not _course:
                            dispatcher.utter_message(
                                text=f"edu.following_course_not_found"
                            )
                            return [FollowupAction("action_listen")]

                        set_slot(sender_id, "current_lecture", "")
                        set_slot(sender_id, "current_step", "")
                        set_slot(
                            sender_id,
                            "current_course",
                            selected_answer["following_action_id"],
                        )
                        set_slot(sender_id, "number_tries", "")
                    else:
                        set_slot(
                            sender_id,
                            "current_step",
                            selected_answer["following_action_id"],
                        )
                else:
                    response = ""
                    try:
                        _sorted_events = sorted(
                            events,
                            key=lambda d: d["timestamp"],
                        )
                        chat = "\n".join(
                            [
                                f"bot: {get_utterances(_sorted_events, False, 1)}",
                                f"uživatel: {get_utterances(_sorted_events, True, 1)}",
                                f"bot: {get_utterances(_sorted_events, False)}",
                                f"uživatel: {latest_message}"
                            ]
                        )
                        #print(f"chat: {chat}", flush=True)
                        prompt = "\n".join([
                            "Krátce odpověz uživateli.",
                            "Níže máš informace, které se ti můžou hodit, ale nepoužívej je za každou cenu.",
                            "Napiš krátkou odpověď do chatu, nepiš bot.",
                            "",
                            "informace:",
                            "Jsi příjemný EDU AI asistent pro studenty a učitele.",
                            "Vznikl jsi ve spolupráci Asociace, NPI ČR a Karlovy Univerzity (2021-23).",
                            "Spojuješ garantovaný vzdělávací obsah s funkcemi GPT a jsi bezplatný.",
                            "V EDU AI editoru si lidé mohou vytvořit vlastního chatbota.",
                            "Pomáháš s matematikou a přípravou na SŠ (lekce od Pedagogické fakulty UK).",
                            "Přípravku najdeš zde: https://edu-ai.eu/kurzy/.",
                            "Testuješ znalosti a povzbuzuješ žáky zábavnou formou.",
                            "Na jaře 2024 přípravku využilo přes 30 000 uživatelů.",
                            "Spolu s NPI ČR připravujeme workshopy a soutěž 'Nachytej AI'.",
                            "Více na: https://edu-ai.eu/ai-pro-skoly/.",
                            "Pomáhej s úlohami, ale neprozrazuj hned odpověď, veď uživatele k řešení.",
                            "Buď pozitivní a udržuj zábavnou konverzaci.",
                            "Odpovídej stručně.",
                            "Nevedeš konverzaci, ale reaguješ na uživatelovy otázky.",
                            "Zatím neumíš spouštět kurzy a určovat průběh lekce, ale v budoucnu dostaneš tuto funkcionalitu.",
                            "Pokud uživatel odpovídá na položenou otázku, nebo vybírá některou z odpovědí odpověz takto: -t-<označení odpovědi>.",
                        ])
                        message = prompt + "průběh konverzace:\n" + chat

                        response = await get_llm_response(message)
                        print(f"full timer: {round(time.time() - timer, 4)}", flush=True)
                        print(f"openai response: {response}", flush=True)

                                                # ...existing code...
                        
                        if "-t-" in response:
                            selected_button = response.split('-t-')[1][:1].lower()
                            #sorry for the mess, but it's a quick fix
                            button_payloads = {chr(97 + i): answer.get("text2match", "") for i, answer in enumerate(answers)}
                            selected_payload = button_payloads.get(selected_button, "")
                        
                            # Process the selected payload
                            if selected_payload:
                                latest_message = selected_payload
                                print(f"selected_payload: {selected_payload}", flush=True)
                                set_slot(sender_id, "latest_message2check", latest_message)
                                                        
                            # Evaluate the latest_message like a button payload
                            if latest_message != "EXTERNAL: EXTERNAL_reminder":
                                set_slot(sender_id, "latest_message2check", latest_message)
                            else:
                                latest_message = latest_message2check
                            
                            if str(step["free_input"]) != "1":
                                selected_answer = next(
                                    (
                                        answer
                                        for answer in answers
                                        if trim_to_50(answer.get("text2match", "")).strip()
                                        == latest_message
                                    ),
                                    None,
                                )
                            else:
                                selected_answer = None
                                if str(steps2go[-1]) == str(step["id"]):
                                    set_slot(sender_id, "current_step", "")
                                    set_slot(
                                        sender_id,
                                        "current_lecture",
                                        get_next_item(lecture_id, lectures2go),
                                    )
                                else:
                                    set_slot(
                                        sender_id,
                                        "current_step",
                                        get_next_item(step["id"], steps2go),
                                    )
                            
                            if selected_answer is not None:
                                if selected_answer["id"] not in delayed_answers:
                                    delayed_answers.append(selected_answer["id"])
                                    set_slot(
                                        sender_id,
                                        "delayed_answers",
                                        json.dumps(delayed_answers),
                                    )
                                    if selected_answer["answer_type"] == "text":
                                        if selected_answer["text2"] not in [None, ""]:
                                            dispatcher.utter_message(
                                                text=f"""{fix_text2send(selected_answer["text2"])}"""
                                            )
                                    elif selected_answer["answer_type"] in ["link", "video"]:
                                        if selected_answer["text2"] not in [None, ""]:
                                            dispatcher.utter_message(
                                                text=f"""{fix_text2send(selected_answer["text2"])}"""
                                            )
                                    elif selected_answer["answer_type"] == "image":
                                        if selected_answer["text2"] not in [None, ""]:
                                            dispatcher.utter_message(
                                                image=f"{os.getenv('PROJECT_URL', '')}/static/uploads/{selected_answer['text2']}"
                                            )
                                    elif selected_answer["answer_type"] == "pause":
                                        if selected_answer["text2"] in [
                                            "seconds",
                                            "minutes",
                                            "hours",
                                            "days",
                                        ]:
                                            trigger_intent_quiz(
                                                sender_id,
                                                units2seconds(
                                                    selected_answer["text2"],
                                                    selected_answer["description"],
                                                ),
                                            )
                                            return [FollowupAction("action_listen")]
                            
                                subanswers = get_db_all(
                                    "select * from lectures_answers where parent_id = %s and step_id = %s order by position",
                                    [selected_answer["id"], step["id"]],
                                )
                                for subanswer in subanswers:
                                    if subanswer["id"] not in delayed_answers:
                                        delayed_answers.append(subanswer["id"])
                                        set_slot(
                                            sender_id,
                                            "delayed_answers",
                                            json.dumps(delayed_answers),
                                        )
                                        if subanswer["answer_type"] == "text":
                                            if subanswer["text2"] not in [None, ""]:
                                                dispatcher.utter_message(
                                                    text=f"""{fix_text2send(subanswer["text2"])}"""
                                                )
                                        elif subanswer["answer_type"] in ["link", "video"]:
                                            if subanswer["text2"] not in [None, ""]:
                                                dispatcher.utter_message(
                                                    text=f"""{fix_text2send(subanswer["text2"])}"""
                                                )
                                        elif subanswer["answer_type"] == "image":
                                            if subanswer["text2"] not in [None, ""]:
                                                dispatcher.utter_message(
                                                    image=f"""{os.getenv('PROJECT_URL', '')}/static/uploads/{subanswer["text2"]}"""
                                                )
                                        elif subanswer["answer_type"] == "pause":
                                            if subanswer["text2"] in [
                                                "seconds",
                                                "minutes",
                                                "hours",
                                                "days",
                                            ]:
                                                trigger_intent_quiz(
                                                    sender_id,
                                                    units2seconds(
                                                        subanswer["text2"], subanswer["description"]
                                                    ),
                                                )
                                                return [FollowupAction("action_listen")]
                            
                                set_slot(sender_id, "delayed_answers", "")
                                set_slot(sender_id, "being_asked", "")
                                set_slot(sender_id, "latest_message2check", "")
                                set_slot(sender_id, "delayed_selected_answers", "")
                            
                                if selected_answer["following_action"] == "next":
                                    if str(steps2go[-1]) == str(step["id"]):
                                        set_slot(sender_id, "current_step", "")
                                        set_slot(
                                            sender_id,
                                            "current_lecture",
                                            get_next_item(lecture_id, lectures2go),
                                        )
                                    else:
                                        set_slot(
                                            sender_id,
                                            "current_step",
                                            get_next_item(step["id"], steps2go),
                                        )
                                        ...
                                elif selected_answer["following_action"] == "again":
                                    ...
                                elif selected_answer["following_action"] == "lecture":
                                    _lecture = get_db_row(
                                        "select * from lectures where id = %s order by id limit 1",
                                        [selected_answer["following_action_id"]],
                                    )
                                    if not _lecture:
                                        dispatcher.utter_message(
                                            text=f"edu.following_lecture_not_found"
                                        )
                                        return [FollowupAction("action_listen")]

                                    set_slot(
                                        sender_id,
                                        "current_lecture",
                                        selected_answer["following_action_id"],
                                    )
                                    set_slot(sender_id, "current_step", "")
                                    set_slot(sender_id, "number_tries", "")

                                elif selected_answer["following_action"] == "course":
                                    _course = get_db_row(
                                        "select * from courses where id = %s order by id limit 1",
                                        [selected_answer["following_action_id"]],
                                    )
                                    if not _course:
                                        dispatcher.utter_message(
                                            text=f"edu.following_course_not_found"
                                        )
                                        return [FollowupAction("action_listen")]

                                    set_slot(sender_id, "current_lecture", "")
                                    set_slot(sender_id, "current_step", "")
                                    set_slot(
                                        sender_id,
                                        "current_course",
                                        selected_answer["following_action_id"],
                                    )
                                    set_slot(sender_id, "number_tries", "")
                                else:
                                    set_slot(
                                        sender_id,
                                        "current_step",
                                        selected_answer["following_action_id"],
                                    )       
                            return[FollowupAction("action_quiz"), SlotSet("NLU_OpenAI2", latest_message),]
                        
                        dispatcher.utter_message(response)
                    except Exception as e:
                        print(f"openai handling error: {e}", flush=True)
                        print(f"Exception type: {type(e)}", flush=True)
                        response = ""
                        dispatcher.utter_message(
                            "Omlouvám se, část mozku mi právě nefunguje."
                        )

                    if response in ["", None]:
                        try:
                            mffcuni = requests.post(
                                os.environ.get("MFF_WIKI_URL", ""),
                                json={"q": latest_message, "exact": 1, "w": 0},
                            )

                            dispatcher.utter_message(mffcuni.json().get("a", ""))
                        except:
                            dispatcher.utter_message(
                                "Omlouvám se, část mozku mi právě nefunguje."
                            )

                    set_slot(sender_id, "being_asked", "")
                    set_slot(sender_id, "number_tries", number_tries)

                return [FollowupAction("action_quiz")]

        elif step["response_type"] == "pause":
            seconds2set = 2
            if step["description"] == "run_at":
                date2run = datetime.datetime.strptime(step["text"], "%d.%m.%Y %H:%M")
                seconds2set = date_seconds_diff(
                    timezone("Europe/Prague").localize(date2run)
                )
            else:
                if step["text2"] in ["seconds", "minutes", "hours", "days"]:
                    seconds2set = units2seconds(step["text2"], step["text"])

            if step["text2"] == "still":
                set_slot(sender_id, "current_step", get_next_item(step["id"], steps2go))

                if str(steps2go[-1]) == str(step["id"]):
                    print("next lecture", flush=True)
                    set_slot(sender_id, "current_step", "")
                    set_slot(
                        sender_id,
                        "current_lecture",
                        get_next_item(lecture_id, lectures2go),
                    )
                    trigger_intent_quiz(sender_id, 1)
                return [
                    SlotSet(
                        "lecture_step",
                        f"{company_id}.{current_course}.{lecture_id}.{step['id']}",
                    ),
                    FollowupAction("action_listen"),
                ]

            if step["description"] in ["after_lection_start", "after_lection_before"]:
                if step["text2"] in ["seconds", "minutes", "hours", "days"]:
                    seconds2set = units2seconds(step["text2"], step["text"])
                else:
                    seconds2set = 2

            if str(steps2go[-1]) == str(step["id"]):
                set_slot(sender_id, "current_step", "")
                set_slot(
                    sender_id, "current_lecture", get_next_item(lecture_id, lectures2go)
                )
            else:
                set_slot(sender_id, "current_step", get_next_item(step["id"], steps2go))
                set_slot(sender_id, "being_asked", "")

            trigger_intent_quiz(sender_id, seconds2set)
            return [
                SlotSet(
                    "lecture_step",
                    f"{company_id}.{current_course}.{lecture_id}.{step['id']}",
                ),
                FollowupAction("action_listen"),
            ]
        else:
            return []

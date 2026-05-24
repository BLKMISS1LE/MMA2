#!/usr/bin/env python3
"""
Meijer Receipt Splitter Mobile

Kivy mobile version of the desktop Meijer Receipt Formatter.
Designed for Android through Buildozer.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import webbrowser
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from plyer import filechooser
except Exception:
    filechooser = None

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import ListProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from meijer_receipt_formatter import ReceiptItem, extract_text, parse_receipt_text


APP_BG = "#07111f"
CARD_BG = "#111c2e"
PANEL_BG = "#0d1728"
TEXT = "#f8fafc"
MUTED = "#93a4b8"
BLUE = "#3478f6"
GREEN = "#16a34a"
RED = "#dc2626"
GOLD = "#fbbf24"


class MLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("font_size", "15sp")
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.bind(size=lambda *_: setattr(self, "text_size", self.size))


class MButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", rgba(BLUE))
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("font_size", "14sp")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(44))
        super().__init__(**kwargs)


def rgba(hex_color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)


def app_dir() -> Path:
    base = getattr(App.get_running_app(), "user_data_dir", None)
    if base:
        path = Path(base)
    else:
        path = Path(__file__).resolve().parent
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_dir() / "split_settings.json"


def history_path() -> Path:
    return app_dir() / "receipt_history.json"


def saved_receipts_dir() -> Path:
    path = app_dir() / "saved_receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path() -> Path:
    return app_dir() / "product_cache.json"


def parse_receipt_datetime(text: str) -> str:
    patterns = [
        r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|A\.M\.|P\.M\.)?)",
        r"(?P<date>\d{4}-\d{1,2}-\d{1,2})\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)?",
        r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        date_text = match.group("date")
        time_text = (match.groupdict().get("time") or "").replace(".", "").strip()
        time_text = re.sub(r"(?i)\s*(AM|PM)$", r" \1", time_text).strip()
        date_formats = ["%m/%d/%Y", "%m/%d/%y"] if "/" in date_text else ["%Y-%m-%d"]
        time_formats = [" %I:%M:%S %p", " %I:%M %p", " %H:%M:%S", " %H:%M", ""] if time_text else [""]
        for date_fmt in date_formats:
            for time_fmt in time_formats:
                try:
                    value = (date_text + (" " + time_text if time_text else "")).strip()
                    parsed = datetime.strptime(value, date_fmt + time_fmt)
                    return parsed.isoformat(timespec="seconds" if time_text else "minutes")
                except ValueError:
                    continue
    return ""


def receipt_date_slug(value: str, fallback: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d")
    except Exception:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value or fallback).strip("-")
        return safe or "receipt"


def format_receipt_date(value: str, fallback: str = "Saved receipt") -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
        date_text = f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
        time_text = parsed.strftime("%I:%M %p").lstrip("0") if parsed.hour or parsed.minute else ""
        return f"{date_text} {time_text}".strip()
    except Exception:
        return value


def receipt_fingerprint(items: list[Any], totals: dict) -> str:
    import hashlib

    def value(item, key: str, default=None):
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)

    payload = {
        "items": [
            {
                "code": value(item, "code", ""),
                "name": value(item, "raw_name", "") or value(item, "display_name", ""),
                "quantity": value(item, "quantity"),
                "unit_price": value(item, "unit_price"),
                "line_total": value(item, "line_total"),
                "discounts": value(item, "discounts", []),
                "adjustments_total": value(item, "adjustments_total", 0.0),
            }
            for item in items
        ],
        "total": (totals or {}).get("total"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def money(value: float | None) -> str:
    return f"${(value or 0.0):.2f}"


class MobileReceiptApp(App):
    title = "Meijer Receipt Splitter"
    status = StringProperty("Import a Meijer digital receipt PDF to start.")
    items = ListProperty([])

    def build(self):
        Window.clearcolor = rgba(APP_BG)
        self.people = self.load_people()
        self.receipt_history = self.load_history()
        self.assignments: dict[int, str] = {}
        self.totals: dict[str, Any] = {}
        self.current_pdf = ""
        self.current_receipt_date = ""
        self.current_receipt_id = ""
        self.current_fingerprint = ""
        self.current_saved_pdf = ""

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        header = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(76), spacing=dp(4))
        header.add_widget(MLabel(text="Meijer Receipt Splitter", font_size="22sp", bold=True, size_hint_y=None, height=dp(34)))
        status_label = MLabel(text=self.status, color=MUTED, font_size="13sp", size_hint_y=None, height=dp(34))
        self.bind(status=lambda _app, value: setattr(status_label, "text", value))
        header.add_widget(status_label)
        root.add_widget(header)

        self.manager = ScreenManager(transition=NoTransition())
        self.manager.add_widget(self.build_import_screen())
        self.manager.add_widget(self.build_split_screen())
        self.manager.add_widget(self.build_history_screen())
        self.manager.add_widget(self.build_totals_screen())
        self.manager.add_widget(self.build_people_screen())
        root.add_widget(self.manager)
        root.add_widget(self.build_nav())
        return root

    def build_nav(self):
        nav = GridLayout(cols=5, size_hint_y=None, height=dp(54), spacing=dp(5))
        for text, screen in [("Import", "import"), ("Split", "split"), ("History", "history"), ("Totals", "totals"), ("People", "people")]:
            btn = MButton(text=text, font_size="12sp", background_color=rgba("#1d2a44"), height=dp(50))
            btn.bind(on_release=lambda _btn, s=screen: self.show_screen(s))
            nav.add_widget(btn)
        return nav

    def show_screen(self, name: str):
        self.manager.current = name
        if name == "history":
            self.render_history()
        elif name == "totals":
            self.render_totals_history()
        elif name == "people":
            self.render_people()

    def card(self, orientation="vertical", padding=12, spacing=8):
        box = BoxLayout(orientation=orientation, padding=dp(padding), spacing=dp(spacing), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        return box

    def make_scroll(self, child):
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(child)
        return scroll

    def build_import_screen(self):
        screen = Screen(name="import")
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(4))
        hero = self.card()
        hero.add_widget(MLabel(text="Import receipt PDF", font_size="20sp", bold=True, size_hint_y=None, height=dp(34)))
        hero.add_widget(MLabel(text="Pick a Meijer digital receipt PDF from your phone. The app extracts the items, saves the original PDF copy, and lets you split totals by person.", color=MUTED, font_size="14sp", size_hint_y=None, height=dp(70)))
        pick = MButton(text="Choose PDF", background_color=rgba(BLUE), height=dp(52))
        pick.bind(on_release=lambda *_: self.choose_pdf())
        hero.add_widget(pick)
        self.selected_pdf_label = MLabel(text="No PDF selected", color=MUTED, font_size="13sp", size_hint_y=None, height=dp(30))
        hero.add_widget(self.selected_pdf_label)
        content.add_widget(hero)

        actions = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(52))
        open_pdf = MButton(text="Open Original PDF", background_color=rgba("#334155"))
        open_pdf.bind(on_release=lambda *_: self.open_current_pdf())
        split = MButton(text="Go To Splitter", background_color=rgba(GREEN))
        split.bind(on_release=lambda *_: self.show_screen("split"))
        actions.add_widget(open_pdf)
        actions.add_widget(split)
        content.add_widget(actions)

        tip = self.card()
        tip.add_widget(MLabel(text="Phone notes", bold=True, size_hint_y=None, height=dp(28)))
        tip.add_widget(MLabel(text="Android can build this as an APK with Buildozer. iPhone needs a separate iOS build/signing setup, so this package is Android-first.", color=MUTED, size_hint_y=None, height=dp(64)))
        content.add_widget(tip)
        screen.add_widget(content)
        return screen

    def build_split_screen(self):
        screen = Screen(name="split")
        wrapper = BoxLayout(orientation="vertical", spacing=dp(8))
        self.split_list = GridLayout(cols=1, spacing=dp(8), size_hint_y=None, padding=dp(2))
        self.split_list.bind(minimum_height=self.split_list.setter("height"))
        wrapper.add_widget(self.make_scroll(self.split_list))
        self.split_total_bar = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(120), padding=dp(8), spacing=dp(4))
        wrapper.add_widget(self.split_total_bar)
        screen.add_widget(wrapper)
        return screen

    def build_history_screen(self):
        screen = Screen(name="history")
        self.history_list = GridLayout(cols=1, spacing=dp(8), size_hint_y=None, padding=dp(2))
        self.history_list.bind(minimum_height=self.history_list.setter("height"))
        screen.add_widget(self.make_scroll(self.history_list))
        return screen

    def build_totals_screen(self):
        screen = Screen(name="totals")
        self.totals_list = GridLayout(cols=1, spacing=dp(8), size_hint_y=None, padding=dp(2))
        self.totals_list.bind(minimum_height=self.totals_list.setter("height"))
        screen.add_widget(self.make_scroll(self.totals_list))
        return screen

    def build_people_screen(self):
        screen = Screen(name="people")
        wrapper = BoxLayout(orientation="vertical", spacing=dp(8))
        self.people_list = GridLayout(cols=1, spacing=dp(8), size_hint_y=None, padding=dp(2))
        self.people_list.bind(minimum_height=self.people_list.setter("height"))
        wrapper.add_widget(self.make_scroll(self.people_list))
        add = MButton(text="Add Person", background_color=rgba(BLUE), height=dp(50))
        add.bind(on_release=lambda *_: self.add_person())
        wrapper.add_widget(add)
        screen.add_widget(wrapper)
        return screen

    def load_people(self):
        if settings_path().exists():
            try:
                data = json.loads(settings_path().read_text(encoding="utf-8"))
                people = data.get("people") or []
                if people:
                    return people
            except Exception:
                pass
        return [
            {"id": "person_1", "name": "Dan", "color": "#dbeafe"},
            {"id": "person_2", "name": "Person 2", "color": "#fee2e2"},
        ]

    def save_people(self):
        settings_path().write_text(json.dumps({"people": self.people}, indent=2), encoding="utf-8")

    def load_history(self):
        if history_path().exists():
            try:
                data = json.loads(history_path().read_text(encoding="utf-8"))
                return data.get("receipts") or []
            except Exception:
                return []
        return []

    def save_history(self):
        history_path().write_text(json.dumps({"receipts": self.receipt_history[:200]}, indent=2, ensure_ascii=False), encoding="utf-8")

    def choose_pdf(self):
        if filechooser is None:
            self.popup("File picker missing", "The plyer file chooser is not available. Build the APK with the included requirements.")
            return
        try:
            filechooser.open_file(on_selection=self.on_pdf_selected, filters=[("PDF", "*.pdf")])
        except Exception as exc:
            self.popup("Could not open picker", str(exc))

    def on_pdf_selected(self, selection):
        if not selection:
            return
        pdf = Path(selection[0])
        if pdf.suffix.lower() != ".pdf":
            self.popup("PDF needed", "Please select a PDF file.")
            return
        self.current_pdf = str(pdf)
        self.selected_pdf_label.text = pdf.name
        self.status = "Formatting receipt..."
        threading.Thread(target=self.parse_pdf_worker, args=(pdf,), daemon=True).start()

    def parse_pdf_worker(self, pdf: Path):
        try:
            text = extract_text(pdf)
            receipt_date = parse_receipt_datetime(text)
            items, totals = parse_receipt_text(text, online=False, cache_path=cache_path())
            Clock.schedule_once(lambda *_: self.finish_parse(pdf, text, receipt_date, items, totals))
        except Exception as exc:
            Clock.schedule_once(lambda *_: self.popup("Parse error", str(exc)))
            Clock.schedule_once(lambda *_: setattr(self, "status", f"Error: {exc}"))

    def finish_parse(self, pdf: Path, text: str, receipt_date: str, items: list[ReceiptItem], totals: dict):
        fingerprint = receipt_fingerprint(items, totals)
        duplicate = self.find_duplicate(fingerprint)
        if duplicate:
            self.load_receipt_record(duplicate)
            self.status = "Loaded existing saved receipt."
            self.show_screen("split")
            return

        self.items = items
        self.totals = totals or {}
        self.assignments = {}
        self.current_receipt_date = receipt_date
        self.current_fingerprint = fingerprint
        self.current_receipt_id = f"receipt_{fingerprint}"
        self.current_saved_pdf = self.copy_pdf_to_storage(pdf, receipt_date, fingerprint)
        self.save_current_receipt()
        self.render_splitter()
        receipt_total = self.totals.get("total") or sum(item.line_total or 0.0 for item in items)
        self.status = f"Parsed {len(items)} items. Total {money(receipt_total)}."
        self.show_screen("split")

    def copy_pdf_to_storage(self, pdf: Path, receipt_date: str, fingerprint: str) -> str:
        try:
            slug = receipt_date_slug(receipt_date, fingerprint)
            dest = saved_receipts_dir() / f"Meijer_Receipt_{slug}_{fingerprint}.pdf"
            shutil.copy2(str(pdf), str(dest))
            return str(dest)
        except Exception:
            return str(pdf)

    def find_duplicate(self, fingerprint: str):
        for receipt in self.receipt_history:
            if receipt.get("fingerprint") == fingerprint:
                return receipt
        return None

    def save_current_receipt(self):
        if not self.items:
            return
        record = {
            "id": self.current_receipt_id or f"receipt_{self.current_fingerprint}",
            "fingerprint": self.current_fingerprint or receipt_fingerprint(self.items, self.totals),
            "receipt_date": self.current_receipt_date,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "source": Path(self.current_pdf).name if self.current_pdf else "Receipt",
            "saved_pdf": self.current_saved_pdf,
            "items": [asdict(item) for item in self.items],
            "totals": self.totals,
            "assignments": {str(k): v for k, v in self.assignments.items()},
            "people": self.people,
        }
        self.receipt_history = [r for r in self.receipt_history if r.get("fingerprint") != record["fingerprint"]]
        self.receipt_history.insert(0, record)
        self.save_history()
        self.render_totals_history()

    def render_splitter(self):
        self.split_list.clear_widgets()
        if not self.items:
            empty = self.card()
            empty.add_widget(MLabel(text="No receipt loaded yet.", bold=True, size_hint_y=None, height=dp(36)))
            empty.add_widget(MLabel(text="Import a PDF first, then assign each item to a person or split it.", color=MUTED, size_hint_y=None, height=dp(52)))
            self.split_list.add_widget(empty)
            self.update_split_totals()
            return
        for index, item in enumerate(self.items):
            self.split_list.add_widget(self.item_card(index, item))
        self.update_split_totals()

    def item_card(self, index: int, item: ReceiptItem):
        assigned = self.assignments.get(index, "")
        bg = self.assignment_color(assigned)
        card = self.card(padding=10, spacing=6)
        card.canvas.before.clear()
        with card.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(*rgba(bg))
            rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(14)])
        card.bind(pos=lambda *_: setattr(rect, "pos", card.pos), size=lambda *_: setattr(rect, "size", card.size))

        top = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42), spacing=dp(8))
        top.add_widget(MLabel(text=f"{item.icon} {item.display_name}", bold=True, color="#0f172a" if bg != CARD_BG else TEXT))
        top.add_widget(MLabel(text=money(item.line_total), bold=True, font_size="18sp", halign="right", color="#0f172a" if bg != CARD_BG else TEXT, size_hint_x=None, width=dp(88)))
        card.add_widget(top)
        meta = f"{item.category} • Qty {item.quantity:g} • #{item.code}"
        if item.discounts:
            meta += f"\n{'; '.join(item.discounts)}"
        card.add_widget(MLabel(text=meta, color="#334155" if bg != CARD_BG else MUTED, font_size="12sp", size_hint_y=None, height=dp(46)))
        if assigned:
            card.add_widget(MLabel(text=f"Assigned: {self.assignment_label(assigned)}", color="#0f172a" if bg != CARD_BG else GOLD, bold=True, size_hint_y=None, height=dp(26)))
        actions = GridLayout(cols=3, spacing=dp(6), size_hint_y=None, height=dp(44))
        assign = MButton(text="Assign", height=dp(42), background_color=rgba(BLUE))
        assign.bind(on_release=lambda *_: self.show_assign_popup(index))
        split = MButton(text="Split", height=dp(42), background_color=rgba(GOLD), color="#111827")
        split.bind(on_release=lambda *_: self.assign_item(index, "__split__"))
        clear = MButton(text="Clear", height=dp(42), background_color=rgba("#475569"))
        clear.bind(on_release=lambda *_: self.assign_item(index, ""))
        actions.add_widget(assign)
        actions.add_widget(split)
        actions.add_widget(clear)
        card.add_widget(actions)
        return card

    def assignment_color(self, assignment: str) -> str:
        if assignment == "__split__":
            return "#fef3c7"
        person = self.person_by_id(assignment)
        return person.get("color", CARD_BG) if person else CARD_BG

    def assignment_label(self, assignment: str) -> str:
        if assignment == "__split__":
            return "Everyone Split"
        person = self.person_by_id(assignment)
        return person.get("name", "") if person else ""

    def show_assign_popup(self, index: int):
        box = GridLayout(cols=1, padding=dp(12), spacing=dp(8), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        popup = Popup(title="Assign item", content=ScrollView(), size_hint=(0.92, 0.75))
        popup.content.add_widget(box)
        for person in self.people:
            btn = MButton(text=person["name"], background_color=rgba(person.get("color", "#dbeafe")), color="#111827")
            btn.bind(on_release=lambda _btn, p=person["id"]: (self.assign_item(index, p), popup.dismiss()))
            box.add_widget(btn)
        split = MButton(text="Split between everyone", background_color=rgba(GOLD), color="#111827")
        split.bind(on_release=lambda *_: (self.assign_item(index, "__split__"), popup.dismiss()))
        box.add_widget(split)
        popup.open()

    def assign_item(self, index: int, assignment: str):
        if assignment:
            self.assignments[index] = assignment
        else:
            self.assignments.pop(index, None)
        self.render_splitter()
        self.save_current_receipt()

    def update_split_totals(self):
        self.split_total_bar.clear_widgets()
        if not self.people:
            self.split_total_bar.add_widget(MLabel(text="Add people to split this receipt.", color=MUTED))
            return
        assigned_totals = {p["id"]: 0.0 for p in self.people}
        split_total = 0.0
        for index, item in enumerate(self.items):
            value = item.line_total or 0.0
            assigned = self.assignments.get(index, "")
            if assigned == "__split__":
                split_total += value
            elif assigned in assigned_totals:
                assigned_totals[assigned] += value
        split_share = split_total / len(self.people) if self.people else 0.0
        receipt_total = self.totals.get("total") or sum(item.line_total or 0.0 for item in self.items)
        line = f"Receipt: {money(receipt_total)}   Split pool: {money(split_total)}"
        self.split_total_bar.add_widget(MLabel(text=line, bold=True, size_hint_y=None, height=dp(28)))
        people_line = "  •  ".join(f"{p['name']}: {money(assigned_totals[p['id']] + split_share)}" for p in self.people)
        self.split_total_bar.add_widget(MLabel(text=people_line or "No totals yet", color=MUTED, size_hint_y=None, height=dp(62)))

    def render_history(self):
        self.history_list.clear_widgets()
        if not self.receipt_history:
            card = self.card()
            card.add_widget(MLabel(text="No saved receipts yet.", bold=True, size_hint_y=None, height=dp(34)))
            self.history_list.add_widget(card)
            return
        for receipt in self.receipt_history:
            self.history_list.add_widget(self.history_card(receipt))

    def history_card(self, receipt: dict):
        card = self.card()
        total = (receipt.get("totals") or {}).get("total")
        if total is None:
            total = sum((item.get("line_total") or 0.0) for item in receipt.get("items", []))
        card.add_widget(MLabel(text=format_receipt_date(receipt.get("receipt_date") or receipt.get("saved_at", "")), bold=True, font_size="18sp", size_hint_y=None, height=dp(32)))
        card.add_widget(MLabel(text=f"{len(receipt.get('items', []))} items • Total {money(total)}", color=MUTED, size_hint_y=None, height=dp(28)))
        totals = self.receipt_person_totals(receipt)
        if totals:
            card.add_widget(MLabel(text="  •  ".join(f"{t['name']}: {money(t['due'])}" for t in totals), color=GOLD, size_hint_y=None, height=dp(44)))
        actions = GridLayout(cols=3, spacing=dp(6), size_hint_y=None, height=dp(44))
        load = MButton(text="Load", background_color=rgba(BLUE))
        load.bind(on_release=lambda *_: self.load_receipt_record(receipt))
        pdf = MButton(text="PDF", background_color=rgba("#334155"))
        pdf.bind(on_release=lambda *_: self.open_pdf(receipt.get("saved_pdf", "")))
        delete = MButton(text="Delete", background_color=rgba(RED))
        delete.bind(on_release=lambda *_: self.delete_receipt(receipt))
        actions.add_widget(load)
        actions.add_widget(pdf)
        actions.add_widget(delete)
        card.add_widget(actions)
        return card

    def load_receipt_record(self, receipt: dict):
        self.current_receipt_id = receipt.get("id", "")
        self.current_fingerprint = receipt.get("fingerprint", "")
        self.current_receipt_date = receipt.get("receipt_date", "")
        self.current_saved_pdf = receipt.get("saved_pdf", "")
        self.current_pdf = self.current_saved_pdf
        self.items = [ReceiptItem(**item) for item in receipt.get("items", [])]
        self.totals = receipt.get("totals", {}) or {}
        self.assignments = {int(k): v for k, v in (receipt.get("assignments", {}) or {}).items()}
        self.render_splitter()
        self.status = "Saved receipt loaded."
        self.show_screen("split")

    def delete_receipt(self, receipt: dict):
        self.receipt_history = [r for r in self.receipt_history if r.get("fingerprint") != receipt.get("fingerprint")]
        saved_pdf = receipt.get("saved_pdf")
        if saved_pdf:
            try:
                path = Path(saved_pdf)
                if path.exists() and path.parent == saved_receipts_dir():
                    path.unlink()
            except Exception:
                pass
        self.save_history()
        self.render_history()
        self.render_totals_history()
        self.status = "Saved receipt deleted."

    def receipt_person_totals(self, receipt: dict):
        people = receipt.get("people") or self.people
        assigned_totals = {p["id"]: 0.0 for p in people if p.get("id")}
        split_total = 0.0
        assignments = receipt.get("assignments", {}) or {}
        for index, item in enumerate(receipt.get("items", [])):
            value = item.get("line_total") or 0.0
            assigned = assignments.get(str(index), "")
            if assigned == "__split__":
                split_total += value
            elif assigned in assigned_totals:
                assigned_totals[assigned] += value
        split_share = split_total / len(people) if people else 0.0
        results = []
        for person in people:
            due = assigned_totals.get(person.get("id"), 0.0) + split_share
            if due > 0:
                results.append({"name": person.get("name", "Person"), "color": person.get("color", "#dbeafe"), "due": due})
        return results

    def render_totals_history(self):
        if not hasattr(self, "totals_list"):
            return
        self.totals_list.clear_widgets()
        totals_by_name: dict[str, dict] = {}
        grand = 0.0
        for receipt in self.receipt_history:
            for total in self.receipt_person_totals(receipt):
                row = totals_by_name.setdefault(total["name"], {"name": total["name"], "due": 0.0, "receipts": 0})
                row["due"] += total["due"]
                row["receipts"] += 1
                grand += total["due"]
        if not totals_by_name:
            card = self.card()
            card.add_widget(MLabel(text="No split totals yet.", bold=True, size_hint_y=None, height=dp(34)))
            self.totals_list.add_widget(card)
            return
        summary = self.card()
        summary.add_widget(MLabel(text=f"All saved split receipts: {money(grand)}", bold=True, font_size="20sp", size_hint_y=None, height=dp(38)))
        self.totals_list.add_widget(summary)
        for entry in sorted(totals_by_name.values(), key=lambda x: x["due"], reverse=True):
            card = self.card()
            card.add_widget(MLabel(text=entry["name"], bold=True, font_size="18sp", size_hint_y=None, height=dp(30)))
            card.add_widget(MLabel(text=f"{money(entry['due'])} across {entry['receipts']} receipt{'s' if entry['receipts'] != 1 else ''}", color=GOLD, size_hint_y=None, height=dp(34)))
            self.totals_list.add_widget(card)

    def render_people(self):
        self.people_list.clear_widgets()
        for person in self.people:
            card = self.card()
            card.add_widget(MLabel(text=person["name"], bold=True, size_hint_y=None, height=dp(30)))
            name_input = TextInput(text=person["name"], multiline=False, size_hint_y=None, height=dp(46), foreground_color=rgba(TEXT), background_color=rgba("#172238"), cursor_color=rgba(TEXT))
            card.add_widget(name_input)
            actions = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(44))
            save = MButton(text="Save Name", background_color=rgba(GREEN))
            save.bind(on_release=lambda _btn, p=person, ti=name_input: self.update_person_name(p, ti.text))
            remove = MButton(text="Remove", background_color=rgba(RED))
            remove.bind(on_release=lambda _btn, p=person: self.remove_person(p["id"]))
            actions.add_widget(save)
            actions.add_widget(remove)
            card.add_widget(actions)
            self.people_list.add_widget(card)

    def add_person(self):
        index = len(self.people) + 1
        palette = ["#fee2e2", "#fef3c7", "#e0e7ff", "#fce7f3", "#ccfbf1", "#e9d5ff"]
        self.people.append({"id": f"person_{index}_{len(self.people)}", "name": f"Person {index}", "color": palette[len(self.people) % len(palette)]})
        self.save_people()
        self.render_people()
        self.render_splitter()

    def update_person_name(self, person: dict, name: str):
        person["name"] = name.strip() or person["name"]
        self.save_people()
        self.render_people()
        self.render_splitter()
        self.save_current_receipt()

    def remove_person(self, person_id: str):
        self.people = [p for p in self.people if p["id"] != person_id]
        self.assignments = {i: v for i, v in self.assignments.items() if v != person_id}
        self.save_people()
        self.render_people()
        self.render_splitter()
        self.save_current_receipt()

    def person_by_id(self, person_id: str):
        for person in self.people:
            if person.get("id") == person_id:
                return person
        return None

    def open_current_pdf(self):
        self.open_pdf(self.current_saved_pdf or self.current_pdf)

    def open_pdf(self, path_value: str):
        if not path_value:
            self.popup("No PDF", "This receipt does not have a saved original PDF yet.")
            return
        path = Path(path_value)
        if not path.exists():
            self.popup("Missing PDF", f"The saved PDF could not be found:\n{path}")
            return
        try:
            if sys.platform == "android":
                from android import mActivity
                from android.content import Intent
                from android.net import Uri
                from java.io import File

                intent = Intent(Intent.ACTION_VIEW)
                intent.setDataAndType(Uri.fromFile(File(str(path))), "application/pdf")
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                mActivity.startActivity(intent)
            else:
                webbrowser.open(path.as_uri())
        except Exception as exc:
            self.popup("Could not open PDF", str(exc))

    def popup(self, title: str, message: str):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        box.add_widget(MLabel(text=message, color=TEXT))
        close = MButton(text="OK", background_color=rgba(BLUE))
        box.add_widget(close)
        popup = Popup(title=title, content=box, size_hint=(0.9, 0.45))
        close.bind(on_release=popup.dismiss)
        popup.open()


if __name__ == "__main__":
    MobileReceiptApp().run()

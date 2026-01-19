# screens/add.py
import json
from datetime import datetime

from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label as KivyLabel
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner

from celebrations_core import load_birthdays
from config import CONFIG_PATH


class AddEntryScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.softinput_mode = 'below_target'

        main_layout = BoxLayout(orientation='vertical')

        scroll = ScrollView(size_hint=(1, 0.9))
        form = BoxLayout(orientation='vertical', size_hint_y=0.6, spacing=10, padding=10)
        form.bind(minimum_height=form.setter('height'))

        gender_row = BoxLayout(size_hint_y=0.14, spacing=5)
        gender_label = KivyLabel(text="Gender:", size_hint=(0.2, 1), halign='right', valign='middle')
        gender_label.bind(size=gender_label.setter('text_size'))

        self.gender_spinner = Spinner(
            text="(optional)",
            values=["m", "f"],
            size_hint=(0.8, 1)
        )

        gender_row.add_widget(gender_label)
        gender_row.add_widget(self.gender_spinner)
        form.add_widget(gender_row)

        def field_row(label_text, input_widget):
            box = BoxLayout(size_hint_y=0.14, spacing=5)
            label = KivyLabel(text=label_text, size_hint=(0.2, 1), halign='right', valign='middle')
            label.bind(size=label.setter('text_size'))
            input_widget.size_hint = (0.8, 1)
            box.add_widget(label)
            box.add_widget(input_widget)
            return box

        self.name_input = TextInput(hint_text="Full Name", multiline=False)
        self.nickname_input = TextInput(hint_text="Nickname", multiline=False)
        self.birth_input = TextInput(hint_text="YYYY-MM-DD", multiline=False)
        self.hint_input = TextInput(hint_text="Hint (optional)", multiline=False)
        self.gender_input = TextInput(hint_text="m / f (optional)", multiline=False)

        self.nonhuman_chk = CheckBox(size_hint=(None, None), size=(32, 32))
        self.deceased_chk = CheckBox(size_hint=(None, None), size=(32, 32))

        form.add_widget(field_row("Name:", self.name_input))
        form.add_widget(field_row("Nickname:", self.nickname_input))
        form.add_widget(field_row("Birthdate:", self.birth_input))
        form.add_widget(field_row("Hint:", self.hint_input))
        form.add_widget(field_row("Gender:", self.gender_input))

        def checkbox_row(label_text, checkbox):
            box = BoxLayout(size_hint_y=0.15, padding=(10, 0), spacing=5)
            label = KivyLabel(text=label_text, size_hint=(0.9, 1), halign='right', valign='middle')
            label.bind(size=label.setter('text_size'))
            box.add_widget(label)
            box.add_widget(checkbox)
            return box

        form.add_widget(checkbox_row("Nonhuman?", self.nonhuman_chk))
        form.add_widget(checkbox_row("Deceased?", self.deceased_chk))

        scroll.add_widget(form)
        main_layout.add_widget(scroll)

        btn_box = BoxLayout(size_hint=(1, 0.1), spacing=10, padding=(10, 10))
        btn_box.add_widget(Button(text="Add", on_press=self.add_entry))
        btn_box.add_widget(Button(text="Lookup", on_press=self.switch_to_lookup))

        main_layout.add_widget(btn_box)
        self.add_widget(main_layout)

    def add_entry(self, _):
        name = self.name_input.text.strip()
        nickname = self.nickname_input.text.strip()
        birth = self.birth_input.text.strip()
        hint = self.hint_input.text.strip()
        gender = 'm' if self.gender_m.state == 'down' else 'f' if self.gender_f.state == 'down' else ''
        nonhuman = self.nonhuman_chk.active
        deceased = self.deceased_chk.active

        if not name:
            self.show_popup("Name is required.")
            return

        try:
            dt = datetime.strptime(birth, "%Y-%m-%d")
            if len(birth.split("-")[0]) < 4:
                raise ValueError("Year must be 4 digits")
        except Exception:
            self.show_popup("Birthdate must be in format YYYY-MM-DD with a 4-digit year.")
            return

        new_entry = {"name": name, "birthdate": birth}
        if nickname:
            new_entry["nickname"] = nickname
        if hint:
            new_entry["hint"] = hint
        if gender in ("m", "f"):
            new_entry["gender"] = gender
        if nonhuman:
            new_entry["nonhuman"] = True
        if deceased:
            new_entry["deceased"] = True

        data = load_birthdays(CONFIG_PATH)
        data.append(new_entry)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        self.show_popup(f"🎉 Added {name} successfully!")
        self.clear_fields()

    def clear_fields(self):
        self.name_input.text = ""
        self.nickname_input.text = ""
        self.birth_input.text = ""
        self.hint_input.text = ""
        self.gender_input.text = ""
        self.nonhuman_chk.active = False
        self.deceased_chk.active = False

    def show_popup(self, message):
        label = KivyLabel(
            text=message,
            halign='center',
            valign='middle'
        )
        label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
        popup = Popup(title="Info", content=label, size_hint=(0.8, 0.3))
        popup.open()

    def switch_to_lookup(self, _):
        self.manager.current = 'lookup'

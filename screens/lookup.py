# screens/lookup.py
from collections import defaultdict
from datetime import datetime

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label as KivyLabel
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from celebrations_core import get_today
from config import CONFIG_PATH
from screens.base import BaseCelebrationScreen
from ui_utils import export_ical, export_config, import_config_file
from utils import extract_messages, render_output, get_celebration_output


class SmartLookupScreen(BaseCelebrationScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.softinput_mode = 'below_target'

        main_layout = BoxLayout(orientation='vertical')

        # 🔍 Top 10% - date, name, lookup
        input_row = BoxLayout(size_hint=(1, 0.1), spacing=5, padding=5)
        self.date_input = TextInput(hint_text="YYYY-MM-DD", multiline=False, size_hint=(0.2, 1))
        self.days_input = TextInput(hint_text="Days", multiline=False, input_filter='int', size_hint=(0.15, 1))
        self.name_input = TextInput(hint_text="Name", multiline=False, size_hint=(0.3, 1))
        lookup_button = Button(text="Lookup", on_press=self.lookup, size_hint=(0.2, 1))
        reset_button = Button(text="Reset", on_press=self.reset_lookup_fields, size_hint=(0.15, 1))
        input_row.add_widget(self.date_input)
        input_row.add_widget(self.days_input)
        input_row.add_widget(self.name_input)
        input_row.add_widget(lookup_button)
        input_row.add_widget(reset_button)
        main_layout.add_widget(input_row)

        # 📜 Middle 80% - Scrollable results
        scroll = ScrollView(size_hint=(1, 0.8), do_scroll_x=False)
        self.output_label = KivyLabel(
            text="🔍 Lookup - Search by name, date, or both",
            markup=True,
            size_hint_y=None,
            halign='left',
            valign='top',
            text_size=(Window.width * 0.95, None)
        )
        self.output_label.bind(texture_size=self.update_label_height)
        scroll.add_widget(self.output_label)
        main_layout.add_widget(scroll)

        bottom_buttons = BoxLayout(size_hint=(1, 0.1), spacing=10, padding=(10, 10))
        
        bottom_buttons.add_widget(Button(text="Copy", on_press=self.copy_to_clipboard))
        bottom_buttons.add_widget(Button(text="Add", on_press=self.switch_to_add))
        bottom_buttons.add_widget(Button(text="Export", on_press=self.export_config))
        bottom_buttons.add_widget(Button(text="Import", on_press=self.import_config))
        bottom_buttons.add_widget(Button(text="iCal", on_press=self.export_ical_file))
        
        main_layout.add_widget(bottom_buttons)

        self.add_widget(main_layout)
        self.lookup_results = []

        today = get_today().isoformat()
        self.date_input.text = today
        Clock.schedule_once(lambda dt: self.on_enter(), 0.1)

    def update_label_height(self, instance, value):
        self.output_label.height = self.output_label.texture_size[1]

    def lookup(self, _):
        date_str = self.date_input.text.strip()
        days_text = self.days_input.text.strip()
        name_query = self.name_input.text.strip().lower()
    
        try:
            lookup_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else get_today()
        except ValueError:
            self.output_text = "Invalid date. Use YYYY-MM-DD format."
            self.output_label.text = self.output_text
            return
    
        days_ahead = int(days_text) if days_text.isdigit() else 0
    
        messages, self.lookup_results = get_celebration_output(
            name=name_query,
            date=lookup_date,
            days_ahead=days_ahead,
            markup=True,
            config_path=CONFIG_PATH
        )
    
        self.output_text = render_output(messages)
        self.output_label.text = self.output_text

    def copy_to_clipboard(self, _):
        copied_text = "\n".join(extract_messages(self.lookup_results, category_filter=("date_header", "label", "celebration"), markup=False))
        Clipboard.copy(copied_text)
        self.show_toast("Copied to clipboard!")

    def show_toast(self, message):
        popup = Popup(
            title="",
            content=KivyLabel(text=message),
            size_hint=(0.5, 0.15),
            auto_dismiss=True
        )
        popup.open()
        Clock.schedule_once(lambda dt: popup.dismiss(), 1.2)

    def export_ical_file(self, _):
        if not self.lookup_results:
            self.show_toast("No results to export.")
            return
        export_ical(self.lookup_results)

    def reset_lookup_fields(self, _):
        self.date_input.text = ""
        self.days_input.text = ""
        self.name_input.text = ""
        self.output_label.text = "🔍 Lookup - Search by name, date, or both"

    def switch_to_add(self, _):
        self.manager.current = 'add'
    
    def import_config(self, _):
        import_config()
        self.show_toast("Imported config and reloaded.")
        self.lookup(None)
    
    def export_config(self, _):
        export_config()

    def on_enter(self):
        # Triggers when screen is displayed
        self.lookup(None)


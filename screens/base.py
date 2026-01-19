# screens/base.py
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView


class BaseCelebrationScreen(Screen):
    def create_scroll_output(self):
        wrapper = BoxLayout(orientation='vertical', size_hint_y=None, padding=10)
        label = Label(
            text="Loading...",
            markup=True,
            size_hint_y=None,
            halign="left",
            valign="top"
        )
        label.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1]))
        label.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
        wrapper.bind(minimum_height=wrapper.setter('height'))
        wrapper.add_widget(label)
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(wrapper)
        return scroll, label

# android_helpers.py
from kivy.utils import platform

if platform == "android":
    from android import activity
    from android.runnable import run_on_ui_thread
    from jnius import autoclass
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup

    from config import CONFIG_DIR, CONFIG_PATH

    REQUEST_CODE_PICK_JSON = 42
    pending_import_callback = None

    @run_on_ui_thread
    def import_config_file():
        Intent = autoclass('android.content.Intent')
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("application/json")
        PythonActivity.mActivity.startActivityForResult(intent, REQUEST_CODE_PICK_JSON)

    def read_uri_to_config(uri):
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity_instance = PythonActivity.mActivity
            content_resolver = activity_instance.getContentResolver()
            input_stream = content_resolver.openInputStream(uri)

            output = b""
            b = input_stream.read()
            while b != -1:
                output += bytes([b])
                b = input_stream.read()
            input_stream.close()

            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, 'wb') as f:
                f.write(output)
        except Exception as e:
            Popup(title="Import Failed", content=Label(text=str(e)), size_hint=(0.9, 0.3)).open()

    def request_storage_permission():
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        permission = autoclass('android.Manifest$permission')
        PythonActivity.mActivity.requestPermissions(
            [permission.READ_EXTERNAL_STORAGE, permission.WRITE_EXTERNAL_STORAGE], 1)

    def register_activity_result_handler():
        # Must be called at runtime on Android
        from android import activity

        def on_activity_result(requestCode, resultCode, intent):
            from android_helpers import (REQUEST_CODE_PICK_JSON,
                                         pending_import_callback)
            if requestCode == REQUEST_CODE_PICK_JSON and resultCode == -1:
                uri = intent.getData()
                read_uri_to_config(uri)
                if pending_import_callback:
                    pending_import_callback(success=True)
            elif pending_import_callback:
                pending_import_callback(success=False)

        # Bind after defining the function, but only when this register function is called
        activity.bind(on_activity_result=on_activity_result)

else:
    # Desktop-safe stubs
    REQUEST_CODE_PICK_JSON = 42
    pending_import_callback = None

    def import_config_file():
        from kivy.uix.label import Label
        from kivy.uix.popup import Popup
        Popup(title="Import Not Supported", content=Label(text="Import is Android-only."), size_hint=(0.8, 0.3)).open()

    def request_storage_permission():
        pass

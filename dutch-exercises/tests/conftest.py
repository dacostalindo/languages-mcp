import os

# The MCP Apps UI tools are opt-in. Enable them for the test process before any test imports the server module;
# test_ui.test_ui_is_off_by_default checks the default in a subprocess.
os.environ["MCP_APPS"] = "1"

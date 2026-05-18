# ui/open_dictionary_dialog.py
import tkinter as tk
from tkinter import filedialog


def ask_open_dictionary(parent):
    return filedialog.askopenfilename(
        parent=parent,
        title="Open Dictionary",
        filetypes=[("JSON Dictionary", "*.json")],
        defaultextension=".json"
    )
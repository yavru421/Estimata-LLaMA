import tkinter as tk
from tkinter import ttk
import sys
import os

def test_gui():
    # Test if tkinter works
    try:
        root = tk.Tk()
        root.title("GUI Test")
        root.geometry("400x300")

        label = ttk.Label(root, text="🎉 GUI is working!", font=('Arial', 16))
        label.pack(pady=50)

        button = ttk.Button(root, text="Close", command=root.quit)
        button.pack(pady=20)

        print("GUI window should be visible now!")
        root.mainloop()

    except Exception as e:
        print(f"GUI Error: {e}")
        print("Tkinter might not be available or there's a display issue")
        return False

    return True

if __name__ == "__main__":
    print("Testing GUI...")
    if test_gui():
        print("GUI test successful!")
    else:
        print("GUI test failed!")

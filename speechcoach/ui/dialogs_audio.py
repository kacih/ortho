import tkinter as tk
from tkinter import ttk, messagebox

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import numpy as np
except Exception:
    np = None

from speechcoach.config import DEFAULT_SAMPLE_RATE

class AudioSettingsDialog(tk.Toplevel):
    def __init__(self, master, audio):
        super().__init__(master)
        self.title("Audio (micro / sortie)")
        self.geometry("820x520")
        self.resizable(True, True)

        self.audio = audio

        if sd is None:
            ttk.Label(self, text="sounddevice n'est pas disponible.").pack(padx=12, pady=12)
            ttk.Button(self, text="Fermer", command=self.destroy).pack(pady=10)
            return

        self.in_list = self.audio.list_input_devices()
        self.out_list = self.audio.list_output_devices()

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(frm, text="Entrée (micro):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0,6))
        self.in_cb = ttk.Combobox(frm, state="readonly", width=100)
        self.in_cb["values"] = [f"{i} — {name}" for i, name in self.in_list]
        self.in_cb.pack(fill="x", pady=6)

        ttk.Label(frm, text="Sortie (HP/casque):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12,6))
        self.out_cb = ttk.Combobox(frm, state="readonly", width=100)
        self.out_cb["values"] = [f"{i} — {name}" for i, name in self.out_list]
        self.out_cb.pack(fill="x", pady=6)

        self._select_current()

        btn = ttk.Frame(frm)
        btn.pack(fill="x", pady=18)
        ttk.Button(btn, text="Tester sortie (bip)", command=self.test_output).pack(side="left")
        ttk.Button(btn, text="Appliquer", command=self.apply).pack(side="left", padx=8)
        ttk.Button(btn, text="Fermer", command=self.destroy).pack(side="right")

    def _select_current(self):
        cur_in = self.audio.input_device
        cur_out = self.audio.output_device
        for k, (i, _n) in enumerate(self.in_list):
            if i == cur_in:
                self.in_cb.current(k)
                break
        for k, (i, _n) in enumerate(self.out_list):
            if i == cur_out:
                self.out_cb.current(k)
                break

    def apply(self):
        try:
            in_sel = int(self.in_cb.get().split("—")[0].strip())
            out_sel = int(self.out_cb.get().split("—")[0].strip())
            self.audio.set_devices(in_sel, out_sel)
            messagebox.showinfo("Audio", "Paramètres audio appliqués.")
        except Exception as e:
            messagebox.showerror("Audio", str(e))

    def test_output(self):
        if sd is None or np is None:
            return
        try:
            out_sel = int(self.out_cb.get().split("—")[0].strip())
            t = np.linspace(0, 0.35, int(DEFAULT_SAMPLE_RATE*0.35), endpoint=False)
            tone = (0.15*np.sin(2*np.pi*880*t)).astype(np.float32)
            sd.play(tone, DEFAULT_SAMPLE_RATE, device=out_sel)
            sd.wait()
        except Exception as e:
            messagebox.showerror("Test sortie", str(e))

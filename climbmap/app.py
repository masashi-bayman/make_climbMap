"""Tkinter GUI アプリケーション。

使い方の流れ:
    1. 「GPXを開く」で地名入りGPX（ヤマレコで変換したもの）を読み込む
    2. 回転・余白を調整（変更すると自動で再描画）
    3. 地名ラベルをドラッグして位置を微調整
    4. 必要なら方向矢印を配置
    5. 「保存」で透過PNGと到着時刻テキストを出力
"""

import os
import sys
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("Agg")  # Tkへの描画は FigureCanvasTkAgg 経由で行う

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .fonts import setup_japanese_font
from .gpx import GpxData, format_waypoint_times, parse_gpx
from .rendering import Arrow, RenderSettings, render_map, save_png

# ラベルドラッグ時、マーカーのX座標にスナップする距離（表示幅に対する比率）
SNAP_RATIO = 0.005


class ClimbMapApp:
    def __init__(self, root: tk.Tk, gpx_path: str | None = None):
        self.root = root
        self.root.title("登山マップ作成 - GPX軌跡プレビュー＆スポット到着時刻")
        self.root.geometry("900x1000")

        self.font_name = setup_japanese_font()

        # データ・描画状態
        self.gpx_data: GpxData | None = None
        self.gpx_path: str | None = None
        self.render = None                    # MapRender
        self.canvas_tk = None                 # FigureCanvasTkAgg
        self.label_positions: dict[str, tuple[float, float]] = {}

        # ドラッグ状態
        self._drag_item = None
        self._drag_offset = (0.0, 0.0)

        # 設定変数
        self.rotation_var = tk.IntVar(master=root, value=0)
        self.top_margin_var = tk.DoubleVar(master=root, value=2.5)
        self.bottom_margin_var = tk.DoubleVar(master=root, value=2.5)
        self.left_margin_var = tk.DoubleVar(master=root, value=1.0)
        self.right_margin_var = tk.DoubleVar(master=root, value=1.0)
        self.arrow_x_var = tk.StringVar(master=root, value="")
        self.arrow_y_var = tk.StringVar(master=root, value="")
        self.arrow_angle_var = tk.StringVar(master=root, value="0")

        self._build_ui()

        if self.font_name is None:
            self.set_status("警告: 日本語フォントが見つかりません。地名が正しく表示されない可能性があります。")

        if gpx_path:
            self.root.after(100, lambda: self.load_gpx(gpx_path))

    # ===== UI構築 =====

    def _build_ui(self):
        controls = ttk.Frame(self.root, padding=5)
        controls.pack(side="top", fill="x")

        # --- ファイル・保存 ---
        frame_file = ttk.LabelFrame(controls, text="ファイル", padding=5)
        frame_file.pack(side="left", padx=3, fill="y")

        ttk.Button(frame_file, text="GPXを開く",
                   command=self.open_gpx).pack(side="left", padx=2)
        ttk.Button(frame_file, text="保存",
                   command=self.save_outputs).pack(side="left", padx=2)

        # --- 回転 ---
        frame_rot = ttk.LabelFrame(controls, text="回転（度）", padding=5)
        frame_rot.pack(side="left", padx=3, fill="y")

        for ang in (0, 90, 180, 270):
            ttk.Button(frame_rot, text=f"{ang}°", width=5,
                       command=lambda a=ang: self.set_rotation(a)
                       ).pack(side="left", padx=1)

        self.entry_rotation = ttk.Entry(frame_rot, width=5)
        self.entry_rotation.insert(0, "0")
        self.entry_rotation.pack(side="left", padx=3)
        self.entry_rotation.bind("<Return>", lambda e: self.apply_custom_rotation())
        ttk.Button(frame_rot, text="適用",
                   command=self.apply_custom_rotation).pack(side="left", padx=1)

        # --- 余白 ---
        frame_margin = ttk.LabelFrame(controls, text="余白（軌跡サイズに対する倍率）", padding=5)
        frame_margin.pack(side="left", padx=3, fill="y")

        for label, var in (("上", self.top_margin_var),
                           ("下", self.bottom_margin_var),
                           ("左", self.left_margin_var),
                           ("右", self.right_margin_var)):
            ttk.Label(frame_margin, text=label).pack(side="left", padx=(4, 1))
            entry = ttk.Entry(frame_margin, width=5, textvariable=var)
            entry.pack(side="left")
            entry.bind("<Return>", lambda e: self.apply_margins())
        ttk.Button(frame_margin, text="適用",
                   command=self.apply_margins).pack(side="left", padx=4)

        # --- 矢印 ---
        frame_arrow = ttk.LabelFrame(controls, text="方向矢印", padding=5)
        frame_arrow.pack(side="left", padx=3, fill="y")

        ttk.Button(frame_arrow, text="位置をクリックで指定",
                   command=self.pick_arrow_position).pack(side="left", padx=2)
        ttk.Label(frame_arrow, text="角度").pack(side="left", padx=(4, 1))
        entry_angle = ttk.Entry(frame_arrow, width=5,
                                textvariable=self.arrow_angle_var)
        entry_angle.pack(side="left")
        entry_angle.bind("<Return>", lambda e: self.redraw())
        ttk.Button(frame_arrow, text="描画",
                   command=self.redraw).pack(side="left", padx=2)
        ttk.Button(frame_arrow, text="消去",
                   command=self.clear_arrow).pack(side="left", padx=2)

        # --- ステータスバー ---
        self.lbl_status = ttk.Label(self.root, text="GPXファイルを開いてください", anchor="w")
        self.lbl_status.pack(fill="x", padx=5, pady=2)

        # --- 地図表示エリア ---
        self.panel_img = tk.Frame(self.root, width=600, height=600, bg="black")
        self.panel_img.pack(fill="both", expand=True, padx=5, pady=5)

        # --- 到着時刻テキスト ---
        font = (self.font_name, 11) if self.font_name else (None, 11)
        self.text_box = tk.Text(self.root, height=8, width=40, font=font)
        self.text_box.pack(pady=2, padx=5, fill="x")

        ttk.Label(self.root,
                  text="↑ このエリアから到着時刻をコピペできます（保存時にこの内容がテキストファイルになります）"
                  ).pack(pady=(0, 4))

    def set_status(self, text: str):
        self.lbl_status.config(text=text)

    # ===== GPX読み込み =====

    def open_gpx(self):
        initial_dir = os.path.dirname(self.gpx_path) if self.gpx_path else None
        path = filedialog.askopenfilename(
            filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")],
            initialdir=initial_dir,
        )
        if path:
            self.load_gpx(path)

    def load_gpx(self, path: str):
        try:
            data = parse_gpx(path)
        except Exception as e:
            messagebox.showerror("エラー", f"GPXの読み込みに失敗しました\n{e}")
            return

        self.gpx_data = data
        self.gpx_path = path
        self.label_positions = {}

        if not data.waypoints:
            messagebox.showwarning(
                "地名がありません",
                "このGPXには地名（ウェイポイント）が含まれていません。\n"
                "ヤマレコで地名入りGPXに変換してから読み込んでください。\n"
                "（軌跡のみで描画します）",
            )

        self.redraw()

        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, format_waypoint_times(data.waypoints))

        self.set_status(
            f"読み込み完了: {os.path.basename(path)}"
            f"（スポット {len(data.waypoints)} 件）"
            " — ラベルはドラッグで調整できます"
        )

    # ===== 描画 =====

    def _current_settings(self) -> RenderSettings:
        return RenderSettings(
            angle_deg=self.rotation_var.get(),
            top_margin=self.top_margin_var.get(),
            bottom_margin=self.bottom_margin_var.get(),
            left_margin=self.left_margin_var.get(),
            right_margin=self.right_margin_var.get(),
            arrow=self._current_arrow(),
        )

    def _current_arrow(self) -> Arrow | None:
        x_str = self.arrow_x_var.get().strip()
        y_str = self.arrow_y_var.get().strip()
        if not x_str or not y_str:
            return None
        try:
            return Arrow(
                x=float(x_str),
                y=float(y_str),
                angle_deg=float(self.arrow_angle_var.get() or 0),
            )
        except ValueError:
            return None

    def redraw(self):
        """現在の設定で再描画する。ドラッグ調整したラベル位置は維持される。"""
        if self.gpx_data is None:
            self.set_status("先にGPXファイルを開いてください")
            return

        try:
            settings = self._current_settings()
        except (tk.TclError, ValueError):
            messagebox.showerror("エラー", "回転・余白は数値で指定してください")
            return

        self.render = render_map(
            self.gpx_data, settings,
            font=self.font_name,
            label_positions=self.label_positions,
        )
        self._mount_canvas()

    def _mount_canvas(self):
        if self.canvas_tk is not None:
            self.canvas_tk.get_tk_widget().destroy()
            self.canvas_tk = None

        self.canvas_tk = FigureCanvasTkAgg(self.render.figure,
                                           master=self.panel_img)
        self.canvas_tk.draw()
        self.canvas_tk.get_tk_widget().pack(fill="both", expand=True)

        canvas = self.render.figure.canvas
        canvas.mpl_connect("button_press_event", self._on_press)
        canvas.mpl_connect("motion_notify_event", self._on_motion)
        canvas.mpl_connect("button_release_event", self._on_release)

    # ===== 回転・余白 =====

    def set_rotation(self, angle: int):
        angle = angle % 360
        if angle != self.rotation_var.get():
            # 回転すると座標系が変わるため、ラベルの手動調整はリセット
            self.label_positions = {}
        self.rotation_var.set(angle)
        self.entry_rotation.delete(0, tk.END)
        self.entry_rotation.insert(0, str(angle))
        self.redraw()

    def apply_custom_rotation(self):
        try:
            angle = int(self.entry_rotation.get())
        except ValueError:
            messagebox.showerror("エラー", "回転角は整数（度）で指定してください")
            return
        self.set_rotation(angle)

    def apply_margins(self):
        try:
            self._current_settings()
        except (tk.TclError, ValueError):
            messagebox.showerror("エラー", "余白は数値で指定してください")
            return
        self.redraw()

    # ===== ラベルのドラッグ =====

    def _on_press(self, event):
        if event.inaxes is None or self.render is None:
            return
        if event.x is None or event.y is None:
            return

        renderer = event.canvas.get_renderer()
        for item in self.render.labels:
            bbox = item.text.get_window_extent(renderer)
            if bbox.contains(event.x, event.y):
                if event.xdata is None or event.ydata is None:
                    return
                x0, y0 = item.text.get_position()
                self._drag_item = item
                self._drag_offset = (x0 - event.xdata, y0 - event.ydata)
                break

    def _on_motion(self, event):
        item = self._drag_item
        if item is None or event.inaxes is None:
            return
        if event.xdata is None or event.ydata is None:
            return

        new_x = event.xdata + self._drag_offset[0]
        new_y = event.ydata + self._drag_offset[1]

        # マーカーの真上に近づいたらX座標をスナップ（引き出し線が垂直になる）
        ax = self.render.ax
        snap_threshold = (ax.get_xlim()[1] - ax.get_xlim()[0]) * SNAP_RATIO
        if abs(new_x - item.anchor_x) < snap_threshold:
            new_x = item.anchor_x

        item.text.set_position((new_x, new_y))
        item.line.set_data([item.anchor_x, new_x], [item.anchor_y, new_y])
        event.canvas.draw_idle()

    def _on_release(self, event):
        if self._drag_item is not None:
            # 位置を記録して、余白変更などの再描画後も維持する
            x, y = self._drag_item.text.get_position()
            self.label_positions[self._drag_item.name] = (x, y)
        self._drag_item = None

    # ===== 矢印 =====

    def pick_arrow_position(self):
        if self.render is None:
            messagebox.showinfo("情報", "先にGPXを読み込んでください")
            return

        canvas = self.render.figure.canvas
        self.set_status("地図上でクリックして矢印の位置を指定してください")

        def on_click(event):
            if event.inaxes and event.xdata is not None and event.ydata is not None:
                self.arrow_x_var.set(f"{event.xdata:.4f}")
                self.arrow_y_var.set(f"{event.ydata:.4f}")
                canvas.mpl_disconnect(cid)
                self.redraw()
                self.set_status(
                    f"矢印を配置しました（X={event.xdata:.4f}, Y={event.ydata:.4f}）"
                    " — 角度を変えて「描画」で向きを調整できます"
                )

        cid = canvas.mpl_connect("button_press_event", on_click)

    def clear_arrow(self):
        self.arrow_x_var.set("")
        self.arrow_y_var.set("")
        if self.gpx_data is not None:
            self.redraw()

    # ===== 保存 =====

    def save_outputs(self):
        if self.render is None or self.gpx_data is None:
            messagebox.showinfo("情報", "先にGPXファイルを開いてください")
            return

        # 出力先はGPXファイルと同じ場所の output_YYYYMMDD フォルダ
        base_dir = os.path.dirname(os.path.abspath(self.gpx_path))
        output_dir = os.path.join(
            base_dir, f"output_{datetime.now().strftime('%Y%m%d')}"
        )
        os.makedirs(output_dir, exist_ok=True)

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = os.path.join(output_dir, f"hiking_track_map_{now_str}.png")
        text_path = os.path.join(output_dir, f"spot_times_{now_str}.txt")

        try:
            save_png(self.render, img_path)
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(self.text_box.get("1.0", tk.END).strip())
        except Exception as e:
            messagebox.showerror("エラー", f"保存中に問題が発生しました\n{e}")
            return

        self.set_status(f"保存しました: {img_path}")
        messagebox.showinfo(
            "保存完了",
            f"画像: {img_path}\nテキスト: {text_path}",
        )


def main():
    gpx_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    ClimbMapApp(root, gpx_path=gpx_path)
    root.mainloop()


if __name__ == "__main__":
    main()

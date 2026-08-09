"""Tkinter GUI アプリケーション。

使い方の流れ:
    1. 「GPXを開く」で地名入りGPX（ヤマレコで変換したもの）を読み込む
    2. 右側のスポット一覧で名前の編集・表示/非表示を切り替える
    3. 回転を調整し、地図のドラッグ移動・ホイール拡縮で構図を決める
    4. 地名ラベルをドラッグして位置を微調整
    5. 必要なら方向矢印を配置（↑↓←→ボタンで向き指定）
    6. 「保存」で透過PNGと到着時刻テキストを出力
"""

import os
import subprocess
import sys
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("Agg")  # Tkへの描画は FigureCanvasTkAgg 経由で行う

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .fonts import setup_japanese_font
from .gpx import GpxData, format_waypoint_times, parse_gpx
from .geometry import rotate_points
from .rendering import Arrow, RenderSettings, render_map, save_png
from .settings import load_settings, save_settings

# ラベルドラッグ時、マーカーのX座標にスナップする距離（表示幅に対する比率）
SNAP_RATIO = 0.005

# マーカー（青丸）をつかめる距離（ピクセル）
MARKER_GRAB_PX = 14


def reveal_in_file_manager(path: str):
    """ファイルマネージャでパスを開く。

    ファイルを指定した場合、可能ならそのファイルを選択した状態で開く
    （Windowsのエクスプローラー、macOSのFinder）。
    """
    path = os.path.normpath(os.path.abspath(path))
    is_file = os.path.isfile(path)

    if sys.platform == "win32":
        if is_file:
            # explorer は成功時も終了コード1を返すため、結果は判定しない
            subprocess.run(f'explorer /select,"{path}"')
        else:
            os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", path] if is_file else ["open", path],
                       check=True)
    else:
        target = os.path.dirname(path) if is_file else path
        subprocess.run(["xdg-open", target], check=True)


class ClimbMapApp:
    def __init__(self, root: tk.Tk, gpx_path: str | None = None):
        self.root = root
        self.root.title("登山マップ作成 - GPX軌跡プレビュー＆スポット到着時刻")
        self.root.geometry("1200x1000")

        self.font_name = setup_japanese_font()
        self.settings = load_settings()

        # データ・描画状態
        self.gpx_data: GpxData | None = None
        self.gpx_path: str | None = None
        self.last_saved_path: str | None = None   # 直近に保存した画像のパス
        self.render = None                    # MapRender
        self.canvas_tk = None                 # FigureCanvasTkAgg
        self.label_positions: dict[int, tuple[float, float]] = {}
        self.spot_rows: list[dict] = []       # スポット一覧の行ウィジェット情報
        # 表示範囲 (x_min, x_max, y_min, y_max)。Noneなら自動
        self.view: tuple[float, float, float, float] | None = None

        # ドラッグ状態（ラベル移動／マーカー移動／地図の移動／端での余白調整）
        self._drag_item = None
        self._drag_offset = (0.0, 0.0)
        self._marker_item = None  # ドラッグ中のマーカー
        self._pan_start = None    # (px, py, xlim, ylim)
        self._edge_drag = None    # (edges, lims, bbox) 端ドラッグ中の情報

        # 設定変数
        self.rotation_var = tk.IntVar(master=root, value=0)
        self.compass_var = tk.BooleanVar(master=root, value=False)
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
        # 横に広がりすぎないよう、操作パネルは2段に分ける
        row1 = ttk.Frame(self.root, padding=(5, 5, 5, 0))
        row1.pack(side="top", fill="x")
        row2 = ttk.Frame(self.root, padding=(5, 3, 5, 0))
        row2.pack(side="top", fill="x")

        # --- 1段目: ファイル・保存 ---
        frame_file = ttk.LabelFrame(row1, text="ファイル", padding=5)
        frame_file.pack(side="left", padx=3, fill="y")

        ttk.Button(frame_file, text="GPXを開く",
                   command=self.open_gpx).pack(side="left", padx=2)
        ttk.Button(frame_file, text="保存",
                   command=self.save_outputs).pack(side="left", padx=2)
        ttk.Button(frame_file, text="保存先を開く",
                   command=self.open_output_folder).pack(side="left", padx=2)

        # --- 1段目: 外部サイトへのリンク（GPXの入手・地名付与） ---
        frame_links = ttk.LabelFrame(row1, text="サイトを開く", padding=5)
        frame_links.pack(side="left", padx=3, fill="y")

        ttk.Button(frame_links, text="YAMAP",
                   command=lambda: self.open_url("yamap_url")
                   ).pack(side="left", padx=2)
        ttk.Button(frame_links, text="ヤマレコ",
                   command=lambda: self.open_url("yamareco_url")
                   ).pack(side="left", padx=2)
        ttk.Button(frame_links, text="URL設定",
                   command=self.edit_links).pack(side="left", padx=2)

        # --- 1段目: 表示範囲 ---
        frame_view = ttk.LabelFrame(row1, text="表示範囲", padding=5)
        frame_view.pack(side="left", padx=3, fill="y")

        ttk.Button(frame_view, text="リセット",
                   command=self.reset_view).pack(side="left", padx=2)
        ttk.Checkbutton(frame_view, text="方位記号(N)",
                        variable=self.compass_var,
                        command=self.redraw).pack(side="left", padx=4)

        # --- 2段目: 回転 ---
        frame_rot = ttk.LabelFrame(row2, text="回転（度）", padding=5)
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

        # --- 2段目: 矢印 ---
        frame_arrow = ttk.LabelFrame(row2, text="方向矢印", padding=5)
        frame_arrow.pack(side="left", padx=3, fill="y")

        ttk.Button(frame_arrow, text="位置をクリックで指定",
                   command=self.pick_arrow_position).pack(side="left", padx=2)

        for label, ang in (("→", 0), ("↑", 90), ("←", 180), ("↓", 270)):
            ttk.Button(frame_arrow, text=label, width=3,
                       command=lambda a=ang: self.set_arrow_angle(a)
                       ).pack(side="left", padx=1)

        ttk.Label(frame_arrow, text="角度").pack(side="left", padx=(4, 1))
        entry_angle = ttk.Entry(frame_arrow, width=5,
                                textvariable=self.arrow_angle_var)
        entry_angle.pack(side="left")
        entry_angle.bind("<Return>", lambda e: self.redraw())
        ttk.Button(frame_arrow, text="消去",
                   command=self.clear_arrow).pack(side="left", padx=2)

        # --- 地図の操作方法（常時表示のヒント） ---
        ttk.Label(
            self.root,
            text="地図の操作　ラベル/青丸: ドラッグで移動　余白: 端をドラッグ"
                 "　全体: ドラッグで移動・ホイールで拡大縮小",
            anchor="w", foreground="gray30",
        ).pack(fill="x", padx=8, pady=(3, 0))

        # --- ステータスバー ---
        self.lbl_status = ttk.Label(self.root, text="GPXファイルを開いてください", anchor="w")
        self.lbl_status.pack(fill="x", padx=5, pady=2)

        # --- 中央: 地図（左）＋スポット一覧（右） ---
        center = ttk.Frame(self.root)
        center.pack(fill="both", expand=True, padx=5, pady=5)

        self.panel_img = tk.Frame(center, width=600, height=600, bg="black")
        self.panel_img.pack(side="left", fill="both", expand=True)

        panel_spots = ttk.LabelFrame(center, text="スポット一覧（編集すると地図に反映）",
                                     padding=5)
        panel_spots.pack(side="right", fill="y", padx=(5, 0))

        spot_tools = ttk.Frame(panel_spots)
        spot_tools.pack(side="top", fill="x", pady=(0, 4))
        ttk.Button(spot_tools, text="マーカー位置を全て戻す",
                   command=self.reset_all_marker_positions).pack(side="left")

        # スクロール可能なスポットリスト
        self.spot_canvas = tk.Canvas(panel_spots, width=340,
                                     highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel_spots, orient="vertical",
                                  command=self.spot_canvas.yview)
        self.spot_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.spot_canvas.pack(side="left", fill="both", expand=True)

        self.spot_list_frame = ttk.Frame(self.spot_canvas)
        self._spot_window = self.spot_canvas.create_window(
            (0, 0), window=self.spot_list_frame, anchor="nw")
        self.spot_list_frame.bind(
            "<Configure>",
            lambda e: self.spot_canvas.configure(
                scrollregion=self.spot_canvas.bbox("all")))
        self.spot_canvas.bind(
            "<Configure>",
            lambda e: self.spot_canvas.itemconfigure(
                self._spot_window, width=e.width))

        # マウスホイールでスクロール（Windows / macOS / Linux）
        def _on_mousewheel(event):
            if event.num == 4 or event.delta > 0:
                self.spot_canvas.yview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0:
                self.spot_canvas.yview_scroll(1, "units")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.spot_canvas.bind(seq, _on_mousewheel)
            self.spot_list_frame.bind(seq, _on_mousewheel)

        # --- 到着時刻テキスト ---
        font = (self.font_name, 11) if self.font_name else (None, 11)
        self.text_box = tk.Text(self.root, height=8, width=40, font=font)
        self.text_box.pack(pady=2, padx=5, fill="x")

        ttk.Label(self.root,
                  text="↑ このエリアから到着時刻をコピペできます（スポット編集で自動更新・保存時にこの内容がテキストファイルになります）"
                  ).pack(pady=(0, 4))

    def set_status(self, text: str):
        self.lbl_status.config(text=text)

    # ===== 外部サイトへのリンク =====

    def open_url(self, key: str):
        """設定されたURLを既定のブラウザで開く"""
        url = self.settings.get(key, "").strip()
        if not url:
            messagebox.showinfo("情報", "URLが設定されていません。「URL設定」から入力してください。")
            return
        webbrowser.open(url)
        self.set_status(f"ブラウザで開きました: {url}")

    def edit_links(self):
        """YAMAP / ヤマレコのリンク先URLを編集して保存する"""
        dialog = tk.Toplevel(self.root)
        dialog.title("リンクURLの設定")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        ttk.Label(
            dialog,
            text="各ボタンで開くURLを設定します。\n"
                 "自分のマイページや活動日記のURLを貼り付けてください。",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="w")

        yamap_var = tk.StringVar(master=dialog, value=self.settings["yamap_url"])
        yamareco_var = tk.StringVar(master=dialog,
                                    value=self.settings["yamareco_url"])

        for i, (label, var) in enumerate((("YAMAP", yamap_var),
                                          ("ヤマレコ", yamareco_var)), start=1):
            ttk.Label(dialog, text=label).grid(row=i, column=0,
                                               padx=(10, 4), pady=3, sticky="e")
            ttk.Entry(dialog, textvariable=var, width=55).grid(
                row=i, column=1, padx=(0, 10), pady=3)

        buttons = ttk.Frame(dialog)
        buttons.grid(row=3, column=0, columnspan=2, pady=(6, 10))

        def apply_and_close():
            self.settings["yamap_url"] = yamap_var.get().strip()
            self.settings["yamareco_url"] = yamareco_var.get().strip()
            save_settings(self.settings)
            dialog.destroy()
            self.set_status("リンクURLを保存しました")

        def restore_defaults():
            from .settings import DEFAULTS
            yamap_var.set(DEFAULTS["yamap_url"])
            yamareco_var.set(DEFAULTS["yamareco_url"])

        ttk.Button(buttons, text="保存", command=apply_and_close
                   ).pack(side="left", padx=4)
        ttk.Button(buttons, text="初期値に戻す", command=restore_defaults
                   ).pack(side="left", padx=4)
        ttk.Button(buttons, text="キャンセル", command=dialog.destroy
                   ).pack(side="left", padx=4)

        dialog.grab_set()

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
        self.view = None

        if not data.waypoints:
            messagebox.showwarning(
                "地名がありません",
                "このGPXには地名（ウェイポイント）が含まれていません。\n"
                "ヤマレコで地名入りGPXに変換してから読み込んでください。\n"
                "（軌跡のみで描画します）",
            )

        self._build_spot_list()
        self.redraw()
        self._refresh_times_text()

        self.set_status(
            f"読み込み完了: {os.path.basename(path)}"
            f"（スポット {len(data.waypoints)} 件）"
            " — 右の一覧で名前編集・表示切替、地図上でラベルと青丸をドラッグ調整"
        )

    # ===== スポット一覧パネル =====

    def _build_spot_list(self):
        """スポット一覧の行を作り直す"""
        for child in self.spot_list_frame.winfo_children():
            child.destroy()
        self.spot_rows = []

        if self.gpx_data is None:
            return

        for idx, wp in enumerate(self.gpx_data.waypoints):
            row = ttk.Frame(self.spot_list_frame)
            row.pack(fill="x", pady=1)

            visible_var = tk.BooleanVar(master=self.root, value=wp.visible)
            check = ttk.Checkbutton(
                row, variable=visible_var,
                command=lambda i=idx: self._on_spot_visibility(i))
            check.pack(side="left")

            name_var = tk.StringVar(master=self.root, value=wp.name)
            entry = ttk.Entry(row, textvariable=name_var, width=24)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
            entry.bind("<Return>", lambda e, i=idx: self._on_spot_rename(i))
            entry.bind("<FocusOut>", lambda e, i=idx: self._on_spot_rename(i))

            time_str = wp.arrival_time[-8:] if wp.arrival_time else ""
            ttk.Label(row, text=time_str).pack(side="right")

            # マーカーを動かしたときだけ「戻す」ボタンを出す
            reset_btn = ttk.Button(
                row, text="戻す", width=5,
                command=lambda i=idx: self.reset_marker_position(i))

            self.spot_rows.append({
                "visible_var": visible_var,
                "name_var": name_var,
                "reset_btn": reset_btn,
            })
            self._update_spot_row_state(idx)

    def _update_spot_row_state(self, idx: int):
        """行の「戻す」ボタンの表示を、マーカー移動の有無に合わせる"""
        if idx >= len(self.spot_rows):
            return
        btn = self.spot_rows[idx]["reset_btn"]
        if self.gpx_data.waypoints[idx].is_moved:
            btn.pack(side="right", padx=(2, 4))
        else:
            btn.pack_forget()

    def _on_spot_visibility(self, idx: int):
        wp = self.gpx_data.waypoints[idx]
        wp.visible = self.spot_rows[idx]["visible_var"].get()
        self.redraw()
        self._refresh_times_text()

    def _on_spot_rename(self, idx: int):
        wp = self.gpx_data.waypoints[idx]
        new_name = self.spot_rows[idx]["name_var"].get().strip()
        if not new_name or new_name == wp.name:
            return
        wp.name = new_name
        self.redraw()
        self._refresh_times_text()

    def _refresh_times_text(self):
        if self.gpx_data is None:
            return
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, format_waypoint_times(self.gpx_data.waypoints))

    # ===== 描画 =====

    def _current_settings(self) -> RenderSettings:
        return RenderSettings(
            angle_deg=self.rotation_var.get(),
            arrow=self._current_arrow(),
            view=self.view,
            show_compass=self.compass_var.get(),
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
            messagebox.showerror("エラー", "回転は数値で指定してください")
            return

        # 古いキャンバスへのドラッグ状態を引きずらない
        self._drag_item = None
        self._marker_item = None
        self._pan_start = None
        self._edge_drag = None

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
        canvas.mpl_connect("scroll_event", self._on_scroll)

    # ===== 回転・表示範囲 =====

    def set_rotation(self, angle: int):
        angle = angle % 360
        if angle != self.rotation_var.get():
            # 回転すると座標系が変わるため、ラベルの手動調整と表示範囲はリセット
            self.label_positions = {}
            self.view = None
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

    def reset_view(self):
        """表示範囲を初期状態（自動計算）に戻す"""
        self.view = None
        if self.gpx_data is not None:
            self.redraw()

    def _save_current_view(self):
        """現在の表示範囲を記録し、再描画後も維持されるようにする"""
        ax = self.render.ax
        x_min, x_max = ax.get_xlim()
        y_min, y_max = ax.get_ylim()
        self.view = (x_min, x_max, y_min, y_max)

    # ===== マウス操作（ラベルのドラッグ／地図の移動・拡縮） =====

    # キャンバス端の「つかめる」幅（ピクセル）
    EDGE_GRAB_PX = 14

    def _edges_at(self, event) -> set:
        """カーソルがキャンバスのどの端の近くにあるかを返す"""
        if self.render is None or event.x is None or event.y is None:
            return set()
        bb = self.render.ax.bbox
        t = self.EDGE_GRAB_PX
        if not (bb.x0 - t <= event.x <= bb.x1 + t and
                bb.y0 - t <= event.y <= bb.y1 + t):
            return set()
        edges = set()
        if abs(event.x - bb.x0) < t:
            edges.add("left")
        if abs(event.x - bb.x1) < t:
            edges.add("right")
        if abs(event.y - bb.y0) < t:
            edges.add("bottom")
        if abs(event.y - bb.y1) < t:
            edges.add("top")
        return edges

    def _on_press(self, event):
        if self.render is None:
            return
        if event.x is None or event.y is None:
            return

        # キャンバスの端なら余白調整ドラッグ（軸の外側でもつかめる）
        edges = self._edges_at(event)
        if edges:
            ax = self.render.ax
            bb = ax.bbox
            self._edge_drag = (
                edges,
                (*ax.get_xlim(), *ax.get_ylim()),
                (bb.x0, bb.x1, bb.y0, bb.y1),
            )
            return

        if event.inaxes is None:
            return

        # ラベルへのヒットを判定（ラベルのドラッグを優先）
        renderer = event.canvas.get_renderer()
        for item in self.render.labels:
            bbox = item.text.get_window_extent(renderer)
            if bbox.contains(event.x, event.y):
                if event.xdata is None or event.ydata is None:
                    return
                x0, y0 = item.text.get_position()
                self._drag_item = item
                self._drag_offset = (x0 - event.xdata, y0 - event.ydata)
                return

        # マーカー（青丸）をつかんだら位置の移動
        marker = self._marker_at(event)
        if marker is not None:
            self._marker_item = marker
            return

        # どれでもなければ地図の移動（パン）
        ax = self.render.ax
        self._pan_start = (event.x, event.y, ax.get_xlim(), ax.get_ylim())

    def _marker_at(self, event):
        """カーソル位置にあるマーカーを返す（無ければ None）"""
        if self.render is None or event.x is None or event.y is None:
            return None
        hit = None
        best = MARKER_GRAB_PX ** 2
        for item in self.render.labels:
            px, py = self.render.ax.transData.transform(
                (item.anchor_x, item.anchor_y))
            d2 = (px - event.x) ** 2 + (py - event.y) ** 2
            if d2 <= best:
                best = d2
                hit = item
        return hit

    def _on_motion(self, event):
        if self._drag_item is not None:
            self._move_label(event)
        elif self._marker_item is not None:
            self._move_marker(event)
        elif self._edge_drag is not None:
            self._resize_edges(event)
        elif self._pan_start is not None:
            self._pan_map(event)
        else:
            self._update_cursor(event)

    def _update_cursor(self, event):
        """端の近くではリサイズカーソルにして、つかめることを示す"""
        if self.canvas_tk is None:
            return
        edges = self._edges_at(event)
        if {"left", "right"} & edges and {"top", "bottom"} & edges:
            cursor = "sizing"
        elif {"left", "right"} & edges:
            cursor = "sb_h_double_arrow"
        elif {"top", "bottom"} & edges:
            cursor = "sb_v_double_arrow"
        elif self._marker_at(event) is not None:
            cursor = "hand2"
        else:
            cursor = ""
        widget = self.canvas_tk.get_tk_widget()
        if widget.cget("cursor") != cursor:
            widget.config(cursor=cursor)

    def _resize_edges(self, event):
        """キャンバス端のドラッグで表示範囲（余白）を調整する"""
        if event.x is None or event.y is None:
            return
        edges, (x_min, x_max, y_min, y_max), (bx0, bx1, by0, by1) = self._edge_drag
        ax = self.render.ax

        # ドラッグ開始時の座標系でピクセル→データ座標に変換
        data_x = x_min + (event.x - bx0) * (x_max - x_min) / (bx1 - bx0)
        data_y = y_min + (event.y - by0) * (y_max - y_min) / (by1 - by0)

        min_w = (x_max - x_min) * 0.05
        min_h = (y_max - y_min) * 0.05

        new_x_min, new_x_max = x_min, x_max
        new_y_min, new_y_max = y_min, y_max
        if "left" in edges:
            new_x_min = min(data_x, x_max - min_w)
        if "right" in edges:
            new_x_max = max(data_x, x_min + min_w)
        if "bottom" in edges:
            new_y_min = min(data_y, y_max - min_h)
        if "top" in edges:
            new_y_max = max(data_y, y_min + min_h)

        ax.set_xlim(new_x_min, new_x_max)
        ax.set_ylim(new_y_min, new_y_max)
        event.canvas.draw_idle()

    def _move_label(self, event):
        item = self._drag_item
        if event.inaxes is None:
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

    def _move_marker(self, event):
        """マーカー（青丸）をドラッグで移動し、引き出し線を追従させる"""
        item = self._marker_item
        if event.inaxes is None:
            return
        if event.xdata is None or event.ydata is None:
            return

        item.anchor_x = event.xdata
        item.anchor_y = event.ydata
        item.marker.set_offsets([[item.anchor_x, item.anchor_y]])

        label_x, label_y = item.text.get_position()
        item.line.set_data([item.anchor_x, label_x], [item.anchor_y, label_y])
        event.canvas.draw_idle()

    def _pan_map(self, event):
        if event.x is None or event.y is None:
            return
        px0, py0, (x_min, x_max), (y_min, y_max) = self._pan_start
        ax = self.render.ax

        # ピクセル移動量をデータ座標に換算して表示範囲をずらす
        dx = (event.x - px0) * (x_max - x_min) / ax.bbox.width
        dy = (event.y - py0) * (y_max - y_min) / ax.bbox.height
        ax.set_xlim(x_min - dx, x_max - dx)
        ax.set_ylim(y_min - dy, y_max - dy)
        event.canvas.draw_idle()

    def _on_release(self, event):
        if self._drag_item is not None:
            # 位置を記録して、再描画後も維持する
            x, y = self._drag_item.text.get_position()
            self.label_positions[self._drag_item.index] = (x, y)
            self._drag_item = None
        if self._marker_item is not None:
            self._store_marker_position(self._marker_item)
            self._marker_item = None
        if self._pan_start is not None:
            self._pan_start = None
            self._save_current_view()
        if self._edge_drag is not None:
            self._edge_drag = None
            self._save_current_view()

    def _store_marker_position(self, item):
        """マーカーの表示位置を回転前の座標に戻して記録する。

        回転前の座標系で持つことで、回転角を変えても移動が保たれる。
        """
        lons, lats, _ = rotate_points(
            [item.anchor_x], [item.anchor_y],
            -self.render.angle_deg, center=self.render.center,
        )
        wp = self.gpx_data.waypoints[item.index]
        wp.moved_lon = lons[0]
        wp.moved_lat = lats[0]
        self._update_spot_row_state(item.index)
        self.set_status(
            f"「{wp.name}」のマーカーを移動しました"
            "（一覧の「戻す」で元の位置に復帰）"
        )

    def reset_marker_position(self, idx: int):
        """1件のマーカー位置をGPX上の座標に戻す"""
        self.gpx_data.waypoints[idx].reset_position()
        self._update_spot_row_state(idx)
        self.redraw()

    def reset_all_marker_positions(self):
        """すべてのマーカー位置をGPX上の座標に戻す"""
        if self.gpx_data is None:
            return
        for idx, wp in enumerate(self.gpx_data.waypoints):
            wp.reset_position()
            self._update_spot_row_state(idx)
        self.redraw()
        self.set_status("すべてのマーカー位置を元に戻しました")

    def _on_scroll(self, event):
        """マウスホイールで拡大縮小（カーソル位置を中心に）"""
        if self.render is None or event.inaxes is None:
            return
        if event.xdata is None or event.ydata is None:
            return

        factor = 0.9 if event.button == "up" else 1.1
        ax = self.render.ax
        x_min, x_max = ax.get_xlim()
        y_min, y_max = ax.get_ylim()
        cx, cy = event.xdata, event.ydata

        ax.set_xlim(cx + (x_min - cx) * factor, cx + (x_max - cx) * factor)
        ax.set_ylim(cy + (y_min - cy) * factor, cy + (y_max - cy) * factor)
        self._save_current_view()
        event.canvas.draw_idle()

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

    def set_arrow_angle(self, angle: int):
        """↑↓←→ボタンから矢印の向きを設定する"""
        self.arrow_angle_var.set(str(angle))
        if self._current_arrow() is not None:
            self.redraw()
        else:
            self.set_status(
                "矢印の位置が未指定です。「位置をクリックで指定」を押して地図をクリックしてください")

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

        self.last_saved_path = img_path
        self.set_status(f"保存しました: {img_path}")

        if messagebox.askyesno(
            "保存完了",
            f"画像: {img_path}\nテキスト: {text_path}\n\n保存先のフォルダを開きますか？",
        ):
            self.open_output_folder()

    def open_output_folder(self):
        """保存先フォルダをファイルマネージャで開く。

        保存済みならその画像を選択した状態で、未保存ならGPXのある場所を開く。
        """
        target = self.last_saved_path
        if target is None or not os.path.exists(target):
            if self.gpx_path is None:
                messagebox.showinfo(
                    "情報", "先にGPXファイルを開くか、画像を保存してください")
                return
            target = os.path.dirname(os.path.abspath(self.gpx_path))

        try:
            reveal_in_file_manager(target)
        except Exception as e:
            messagebox.showerror("エラー", f"フォルダを開けませんでした\n{e}")
            return
        self.set_status(f"フォルダを開きました: {target}")


def main():
    gpx_path = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    ClimbMapApp(root, gpx_path=gpx_path)
    root.mainloop()


if __name__ == "__main__":
    main()

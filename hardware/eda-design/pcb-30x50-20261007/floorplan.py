"""Proposed 30x50 mm floorplan (mm, origin = board top-left, y grows downward).

Both panels are drawn as seen from the FRONT (back side shown x-ray style),
so the same x/y means the same physical spot on the board.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

W, H = 30.0, 50.0

C = {
    "rf": "#d64545", "mcu": "#3b6fb6", "audio": "#8a55c4", "power": "#e08a1e",
    "usb": "#2a9d6f", "conn": "#555555", "ui": "#1e9bb5", "bat": "#b0632e",
}

FRONT = [
    # (x0, y0, w, h, label, color, style)
    (0.0, 0.0, 6.6, 14.6, "天线净空\n两层都不铺铜\n不走线", C["rf"], "keepout"),
    (0.3, 0.5, 16.6, 13.2, "U1 ESP32-C3-MINI-1\n天线朝左 · 贴顶左角", C["mcu"], "part"),
    (24.3, 2.3, 3.0, 2.2, "U4 麦克风", C["audio"], "part"),
    (22.0, 5.2, 7.5, 2.6, "R1 C13（麦克风旁）", C["audio"], "zone"),
    (17.6, 8.4, 11.9, 5.4, "MCU 外围\nC2/C3 去耦 · R9/C15 EN\nR10/R12/R11/R18/R2 · D3/R13", C["mcu"], "zone"),
    (1.0, 15.6, 7.0, 4.0, "R14/R15/C19\nSYS_ADC 分压", C["mcu"], "zone"),
    (9.0, 15.6, 9.8, 6.6, "U3 3V3 LDO\n+C16 10µF（贴模块供电脚）", C["power"], "zone"),
    (26.2, 15.6, 3.3, 5.6, "SW2\nEN", C["ui"], "part"),
    (26.2, 22.0, 3.3, 5.6, "SW3\nBOOT", C["ui"], "part"),
    (25.4, 29.0, 4.1, 3.6, "J4 录音键\n1.25 SMD", C["conn"], "part"),
    (1.0, 21.6, 6.0, 7.1, "U5\nNS4168\n功放", C["audio"], "part"),
    (8.0, 23.2, 8.0, 6.0, "U7 3V3_AMP LDO\nC4 · C5→1206 100µF\nC23", C["audio"], "zone"),
    (16.8, 23.2, 5.6, 7.3, "U2\nETA6002\n充电", C["power"], "part"),
    (17.1, 31.2, 4.4, 4.2, "L1\n4.4×4.2", C["power"], "part"),
    (22.8, 23.2, 2.4, 12.2, "C6\nC7\nC1\nC8\nR3", C["power"], "zone"),
    (1.0, 30.6, 9.5, 5.6, "电池保护 U6 DW01A\nQ1 8205A · R16/R17/C22\n（电芯自带保护板可删）", C["bat"], "zone"),
    (1.4, 40.9, 5.3, 2.7, "J3 喇叭", C["conn"], "part"),
    (10.4, 36.6, 11.2, 5.4, "USB 保护（紧贴 J1 正上方）\nD1/D2 ESD · R6/R7 33Ω\nR4/R5 CC · F1 · R8 · D4", C["usb"], "zone"),
    (11.2, 42.8, 9.1, 5.4, "J1 定位脚穿板\n正面此处不放件", C["usb"], "keepout"),
    (1.4, 45.7, 5.3, 2.7, "J2 插针穿板", C["bat"], "keepout"),
]

BACK = [
    (0.0, 0.0, 6.6, 14.6, "天线净空", C["rf"], "keepout"),
    (0.3, 0.5, 16.6, 13.2, "U1 正下方：完整 GND\n不放件、尽量不走线", C["mcu"], "keepout"),
    (6.6, 14.6, 23.4, 26.0, "整面 GND 铺铜\n只走少量必要的线\n（不放元件 → 单面贴片）", "#7a7a7a", "keepout"),
    (11.2, 42.8, 9.1, 5.4, "J1 立式 USB-C\n（背面，已定）", C["usb"], "part"),
    (1.4, 45.7, 5.3, 2.7, "J2 电池", C["bat"], "part"),
    (1.4, 40.9, 5.3, 2.7, "J3 插针穿板", C["conn"], "keepout"),
]


def draw(ax, items, title):
    ax.add_patch(FancyBboxPatch((0, 0), W, H, boxstyle="round,pad=0,rounding_size=1.0",
                                fc="#1f6f43", ec="#0b3d22", lw=2, alpha=0.18))
    for x, y, w, h, label, color, style in items:
        if style == "keepout":
            ax.add_patch(Rectangle((x, y), w, h, fc="none", ec=color, lw=1.4, ls="--", hatch="///", alpha=0.75))
        elif style == "zone":
            ax.add_patch(Rectangle((x, y), w, h, fc=color, ec=color, lw=1, alpha=0.18))
        else:
            ax.add_patch(Rectangle((x, y), w, h, fc=color, ec="black", lw=0.8, alpha=0.55))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=6.3, color="black")
    for yy in range(0, 51, 10):
        ax.axhline(yy, color="#999", lw=0.3, zorder=0)
    ax.set_xlim(-1, W + 1)
    ax.set_ylim(H + 1, -1)
    ax.set_aspect("equal")
    ax.set_xticks(range(0, 31, 5))
    ax.set_yticks(range(0, 51, 5))
    ax.tick_params(labelsize=7)
    ax.set_title(title, fontsize=10)


fig, axes = plt.subplots(1, 2, figsize=(9.2, 8.6))
draw(axes[0], FRONT, "正面 TOP（所有贴片都在这一面）")
draw(axes[1], BACK, "背面 BOTTOM（从正面透视，坐标同左）")
fig.suptitle("AI_figure 30×50 mm 排布建议（单位 mm，原点=左上角）", fontsize=11)
fig.tight_layout()
fig.savefig(__file__.replace("floorplan.py", "floorplan.png"), dpi=170)
print("ok")

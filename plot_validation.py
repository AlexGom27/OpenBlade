"""Genera gráficas Cl, Cd, Cm vs α comparando simulación vs NASA."""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))

# NASA TM 4074 Tabla I (Re=2.0×10⁶, M=0.15)
NASA = {
    -4.25: {"Cl": -0.430, "Cd": 0.00730, "Cm": -0.0040},
    -2.10: {"Cl": -0.215, "Cd": 0.00620, "Cm": -0.0020},
     0.00: {"Cl":  0.000, "Cd": 0.00620, "Cm":  0.0000},
     1.85: {"Cl":  0.194, "Cd": 0.00620, "Cm":  0.0030},
     4.25: {"Cl":  0.445, "Cd": 0.00670, "Cm":  0.0040},
     6.05: {"Cl":  0.625, "Cd": 0.00870, "Cm":  0.0070},
     8.15: {"Cl":  0.855, "Cd": 0.01270, "Cm":  0.0080},
    10.15: {"Cl":  1.045, "Cd": 0.01350, "Cm":  0.0120},
    11.15: {"Cl":  1.135, "Cd": 0.01490, "Cm":  0.0140},
    12.10: {"Cl":  1.218, "Cd": 0.01640, "Cm":  0.0180},
    13.08: {"Cl":  1.290, "Cd": 0.01880, "Cm":  0.0190},
    14.25: {"Cl":  1.362, "Cd": 0.02280, "Cm":  0.0220},
    15.25: {"Cl":  1.408, "Cd": 0.02910, "Cm":  0.0250},
}


def plot_all():
    results_files = [
        ("results_nasa_polar.json", "k-ω SST (150 pts, 15 BL)", "C0", "o"),
        ("results_nasa_planb_dense.json", "k-ω SST (300 pts, 25 BL)", "C2", "s"),
        ("results_nasa_transition.json", "k-ω SST-LM transición (300 pts)", "C1", "D"),
    ]

    nasa_aoa = sorted(NASA.keys())
    nasa_cl = [NASA[a]["Cl"] for a in nasa_aoa]
    nasa_cd = [NASA[a]["Cd"] for a in nasa_aoa]
    nasa_cm = [NASA[a]["Cm"] for a in nasa_aoa]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    for fname, label, color, marker in results_files:
        path = os.path.join(HERE, fname)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)
        res = [r for r in data["results"] if r.get("ok")]
        aoa = [r["aoa"] for r in res]
        cl = [r["Cl"] for r in res]
        cd = [r["Cd"] for r in res]
        cm = [r["Cm"] for r in res]
        for ax, y, lbl in zip(axes, (cl, cd, cm), ("Cl", "Cd", "Cm")):
            ax.plot(aoa, y, marker + "-", color=color, label=label, linewidth=2, markersize=9)

    for ax, ynasa, name in zip(axes, (nasa_cl, nasa_cd, nasa_cm), ("Cl", "Cd", "Cm")):
        ax.plot(nasa_aoa, ynasa, "k-^", label="NASA TM 4074 (Re=2×10⁶)", linewidth=2, markersize=7)
        ax.set_xlabel("Ángulo de ataque α (°)")
        ax.set_ylabel(name)
        ax.set_title(f"{name} vs α — NACA 0012")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)
        ax.axhline(0, color="gray", lw=0.5)

    axes[1].set_yscale("log")
    axes[1].set_title("Cd vs α (escala log)")

    plt.suptitle("Validación OpenBlade 2D vs NASA TM 4074 — NACA 0012 @ Re=2×10⁶",
                 fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out = os.path.join(HERE, "validacion_nasa_polar.png")
    plt.savefig(out, dpi=120, bbox_inches="tight")
    print(f"Gráfica guardada: {out}")


if __name__ == "__main__":
    plot_all()

# -*- coding: utf-8 -*-
from data.defender import update_defender_stats
from data.forward import update_forward_stats
from data.goalkeeper import update_goalkeeper_stats
from data.midfielder import update_midfielder_stats
from utils.utils import session, forwards

import tkinter as tk
from tkinter import messagebox


def forward_midfielder_params(root, name, position):
    def on_update():
        goals = goals_entry.get()
        assists = assists_entry.get()
        matches = matches_entry.get()
        trophies = trophies_entry.get()
        golden_ball = golden_ball_var.get()
        golden_boot = golden_boot_var.get()

        try:
            if position in forwards:
                update_forward_stats(
                    session=session,
                    name=name,
                    overall=0,
                    team="",
                    position=position,
                    matches=int(matches) if matches else 1,
                    goals=int(goals) if goals else 0,
                    assists=int(assists) if assists else 0,
                    trophies=int(trophies) if trophies else 0,
                    golden_ball=golden_ball,
                    golden_boot=golden_boot
                )
            else:
                update_midfielder_stats(
                    session=session,
                    name=name,
                    overall=0,
                    team="",
                    position=position,
                    matches=int(matches) if matches else 1,
                    goals=int(goals) if goals else 0,
                    assists=int(assists) if assists else 0,
                    trophies=int(trophies) if trophies else 0,
                    golden_ball=golden_ball,
                    golden_boot=golden_boot
                )
            messagebox.showinfo("Успех", f"Статистика игрока {name} обновлена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка: {str(e)}")

    tk.Label(root, text="Матчи").grid(row=3, column=0, padx=10, pady=5)
    matches_entry = tk.Entry(root)
    matches_entry.grid(row=3, column=1, padx=10, pady=5)

    tk.Label(root, text="Голы").grid(row=4, column=0, padx=10, pady=5)
    goals_entry = tk.Entry(root)
    goals_entry.grid(row=4, column=1, padx=10, pady=5)

    tk.Label(root, text="Ассисты").grid(row=5, column=0, padx=10, pady=5)
    assists_entry = tk.Entry(root)
    assists_entry.grid(row=5, column=1, padx=10, pady=5)

    tk.Label(root, text="Трофеи").grid(row=6, column=0, padx=10, pady=5)
    trophies_entry = tk.Entry(root)
    trophies_entry.grid(row=6, column=1, padx=10, pady=5)

    tk.Label(root, text="Золотой мяч").grid(row=7, column=0, padx=10, pady=5)
    golden_ball_var = tk.BooleanVar()
    golden_ball_check = tk.Checkbutton(root, text="Да", variable=golden_ball_var)
    golden_ball_check.grid(row=7, column=1, padx=10, pady=5)

    tk.Label(root, text="Золотая бутса").grid(row=9, column=0, padx=10, pady=5)
    golden_boot_var = tk.BooleanVar()
    golden_boot_check = tk.Checkbutton(root, text="Да", variable=golden_boot_var)
    golden_boot_check.grid(row=9, column=1, padx=10, pady=5)

    update_button = tk.Button(root, text="Обновить статистику игрока", command=on_update)
    update_button.grid(row=10, column=0, columnspan=2, pady=10)


def defender_params(root, name, position):
    def on_update():
        goals = goals_entry.get()
        assists = assists_entry.get()
        matches = matches_entry.get()
        trophies = trophies_entry.get()
        golden_ball = golden_ball_var.get()
        clean_sheets = clean_sheets_entry.get()

        try:
            update_defender_stats(
                session=session,
                name=name,
                overall=0,
                team="",
                position=position,
                matches=int(matches) if matches else 1,
                goals=int(goals) if goals else 0,
                assists=int(assists) if assists else 0,
                trophies=int(trophies) if trophies else 0,
                clean_sheet=int(clean_sheets) if clean_sheets else 0,
                golden_ball=golden_ball,
            )
            messagebox.showinfo("Успех", f"Статистика игрока {name} обновлена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка: {str(e)}")

    tk.Label(root, text="Матчи").grid(row=3, column=0, padx=10, pady=5)
    matches_entry = tk.Entry(root)
    matches_entry.grid(row=3, column=1, padx=10, pady=5)

    tk.Label(root, text="Голы").grid(row=4, column=0, padx=10, pady=5)
    goals_entry = tk.Entry(root)
    goals_entry.grid(row=4, column=1, padx=10, pady=5)

    tk.Label(root, text="Ассисты").grid(row=5, column=0, padx=10, pady=5)
    assists_entry = tk.Entry(root)
    assists_entry.grid(row=5, column=1, padx=10, pady=5)

    tk.Label(root, text="Трофеи").grid(row=6, column=0, padx=10, pady=5)
    trophies_entry = tk.Entry(root)
    trophies_entry.grid(row=6, column=1, padx=10, pady=5)

    tk.Label(root, text="Сухие матчи").grid(row=7, column=0, padx=10, pady=5)
    clean_sheets_entry = tk.Entry(root)
    clean_sheets_entry.grid(row=7, column=1, padx=10, pady=5)

    tk.Label(root, text="Золотой мяч").grid(row=8, column=0, padx=10, pady=5)
    golden_ball_var = tk.BooleanVar()
    golden_ball_check = tk.Checkbutton(root, text="Да", variable=golden_ball_var)
    golden_ball_check.grid(row=8, column=1, padx=10, pady=5)

    update_button = tk.Button(root, text="Обновить статистику игрока", command=on_update)
    update_button.grid(row=10, column=0, columnspan=2, pady=10)


def goalkeeper_params(root, name, position):
    def on_update():
        matches = matches_entry.get()
        trophies = trophies_entry.get()
        missed_goals = missed_goals_entry.get()
        golden_ball = golden_ball_var.get()
        clean_sheets = clean_sheets_entry.get()

        try:
            update_goalkeeper_stats(
                session=session,
                name=name,
                overall=0,
                team="",
                position=position,
                matches=int(matches) if matches else 1,
                missed_goals_per_match=int(missed_goals) if missed_goals else 0,
                trophies=int(trophies) if trophies else 0,
                clean_sheet=int(clean_sheets) if clean_sheets else 0,
                golden_ball=golden_ball,
            )
            messagebox.showinfo("Успех", f"Статистика игрока {name} обновлена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка: {str(e)}")

    tk.Label(root, text="Матчи").grid(row=3, column=0, padx=10, pady=5)
    matches_entry = tk.Entry(root)
    matches_entry.grid(row=3, column=1, padx=10, pady=5)

    tk.Label(root, text="Трофеи").grid(row=4, column=0, padx=10, pady=5)
    trophies_entry = tk.Entry(root)
    trophies_entry.grid(row=4, column=1, padx=10, pady=5)

    tk.Label(root, text="Сухие матчи").grid(row=5, column=0, padx=10, pady=5)
    clean_sheets_entry = tk.Entry(root)
    clean_sheets_entry.grid(row=5, column=1, padx=10, pady=5)

    tk.Label(root, text="Пропущенные голы").grid(row=6, column=0, padx=10, pady=5)
    missed_goals_entry = tk.Entry(root)
    missed_goals_entry.grid(row=6, column=1, padx=10, pady=5)

    tk.Label(root, text="Золотой мяч").grid(row=7, column=0, padx=10, pady=5)
    golden_ball_var = tk.BooleanVar()
    golden_ball_check = tk.Checkbutton(root, text="Да", variable=golden_ball_var)
    golden_ball_check.grid(row=7, column=1, padx=10, pady=5)

    update_button = tk.Button(root, text="Обновить статистику игрока", command=on_update)
    update_button.grid(row=8, column=0, columnspan=2, pady=10)
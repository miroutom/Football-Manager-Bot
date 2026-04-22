class Team:
    def __init__(self, name):
        self.name = name
        self.matches = 0
        self.wins = 0
        self.draws = 0
        self.losses = 0
        self.scored = 0
        self.missed = 0
        # Личные встречи: {opponent_name: {'scored': X, 'missed': Y, 'points': Z}}
        self.head_to_head = {}

    @property
    def difference(self):
        return self.scored - self.missed

    @property
    def points(self):
        return self.wins * 3 + self.draws

    def update_stats(self, scored, missed, opponent=None):
        self.matches += 1
        self.scored += scored
        self.missed += missed

        if scored > missed:
            self.wins += 1
            result_points = 3
        elif scored == missed:
            self.draws += 1
            result_points = 1
        else:
            self.losses += 1
            result_points = 0

        # Сохраняем личные встречи
        if opponent:
            if opponent not in self.head_to_head:
                self.head_to_head[opponent] = {'scored': 0, 'missed': 0, 'points': 0}
            self.head_to_head[opponent]['scored'] += scored
            self.head_to_head[opponent]['missed'] += missed
            self.head_to_head[opponent]['points'] += result_points

    def get_h2h_stats(self, opponent):
        """Получить статистику личных встреч с конкретным соперником"""
        if opponent in self.head_to_head:
            h2h = self.head_to_head[opponent]
            return h2h['points'], h2h['scored'] - h2h['missed'], h2h['scored']
        return 0, 0, 0

    def __repr__(self):
        return f"Team({self.name}, {self.points}pts, {self.difference}gd)"

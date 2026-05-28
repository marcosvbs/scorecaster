def calculate_winner(home_goals, away_goals):
    if home_goals > away_goals:
        return "home"
    elif away_goals > home_goals:
        return "away"
    else:
        return "draw"


def calculate_points(pred_home_goals, pred_away_goals, home_goals, away_goals):
    predicted_winner = calculate_winner(pred_home_goals, pred_away_goals)
    winner = calculate_winner(home_goals, away_goals)

    has_hit_winner = predicted_winner == winner

    is_result_a_draw = has_hit_winner and winner == "draw"
    has_hit_home_goals = pred_home_goals == home_goals
    has_hit_away_goals = pred_away_goals == away_goals

    has_hit_goal_diff = abs(home_goals - away_goals) == abs(
        pred_home_goals - pred_away_goals
    )

    has_hit_exact_score = has_hit_home_goals and has_hit_away_goals

    if has_hit_exact_score:
        return (10, "exact")
    elif is_result_a_draw:
        return (5, "partial")
    elif has_hit_winner and has_hit_goal_diff:
        return (7, "partial")
    elif has_hit_winner:
        return (5, "partial")
    else:
        return (0, "wrong")

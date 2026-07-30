def filter_destinations(destinations, budget, month):
    filtered = []

    for d in destinations:
        if d.avg_cost_per_day <= budget and month in d.best_months:
            filtered.append(d)

    return filtered
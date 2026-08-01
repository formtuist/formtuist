def sum_even(n):
    total = 0
    for i in range(n + 1):
        if i % 2 == 1:
            total += i
    return total

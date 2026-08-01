word = input("Enter a word: ")
vowels = "aeiou"
for char in word.lower():
    if char in vowels:
        count += 1
count = 0
print(f"Vowels: {count}")

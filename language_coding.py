
class LangCodeForm:
    base = 0
    src = 1
    tgt = 2


# each language has 3 names: base name, from-phrase and to-phrase
code2names_rus = {
    "rus": ("русский", "с русского", "на русский"),
    "eng": ("английский", "с английского", "на английский"),
}


def get_lang_name(code: str, code_form_id: int, target_language: str = "rus") -> str:
    line = code2names_rus.get(code)
    if line is None:
        return code
    return line[code_form_id]

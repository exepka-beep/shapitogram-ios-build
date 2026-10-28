"""Teach the iOS client ShapitoGram's own +1337 numbering plan.

Why this exists
---------------
`1337` is not a country calling code, but it starts with `1`, so every client
resolves `+1337...` to the United States:

    lookupCountryIdByNumber("13371233")  ->  (US, code "1")
    formatPhoneNumber(...)               ->  "+1 (337) 123-3"

On the login screen that is fatal: `PhoneInputNode` asks
`AuthorizationSequenceCountrySelectionController.lookupCountryIdByNumber` for a
region prefix through `customFormatter`, gets nil for anything that is not a
real code, and falls back to `phoneFormatter.updateText`, which rewrites the
typed `1` into `+1`. The user cannot enter 1337 at all.

The server does advertise the range as country `ZZ` ("ShapitoGram") through
`help.getCountriesList`, and a client that has that list behaves correctly.
This patch makes the client work regardless: the number is recognised before
any list lookup, so a stale cache, an older server or a failed
`help.getCountriesList` cannot break it.

Two files:

1. `AuthorizationSequenceCountrySelectionController.setupCountryCodes` -- the
   single place where the country list and the prefix map are installed,
   whether from the bundled resource or from the server. If the installed set
   has no `1337` entry, add one. Doing it here instead of in the bundled
   `PhoneCountries.txt` covers both sources.

2. `PhoneNumbers.swift` -- `formatPhoneNumber` is what the profile screen shows.
   Both overloads short-circuit for this range so the number is printed as
   `+13371233` instead of being handed to libphonenumber.

The `1337` string in the guards below is deliberate: it is the one literal this
patch adds, so its presence in a built binary is provable rather than inferred.
"""

import os
import sys

MARKER = "ShapitoGram: +1337 plan"

COUNTRY_TARGET = os.path.join(
    "submodules", "CountrySelectionUI", "Sources",
    "AuthorizationSequenceCountrySelectionController.swift",
)
PHONE_TARGET = os.path.join(
    "submodules", "PhoneNumberFormat", "Sources", "PhoneNumbers.swift",
)

SETUP_ANCHOR = """    public static func setupCountryCodes(countries: [Country], codesByPrefix: [String: (Country, Country.CountryCode)]) {
        countryCodes = countries
        countryCodesByPrefix = codesByPrefix
    }"""

SETUP_REPLACEMENT = """    public static func setupCountryCodes(countries: [Country], codesByPrefix: [String: (Country, Country.CountryCode)]) {
        countryCodes = countries
        countryCodesByPrefix = codesByPrefix

        // ShapitoGram: +1337 plan.
        //
        // 1337 is not a calling code but begins with "1", so without an entry
        // here the login screen resolves it to the USA and rewrites the typed
        // "1" into "+1" -- the number can never be entered. The server lists
        // the range as country ZZ; do not depend on that list having arrived.
        if countryCodesByPrefix["1337"] == nil {
            let shapitoGramCode = Country.CountryCode(code: "1337", prefixes: [], patterns: ["XXXXX"])
            let shapitoGram = Country(
                id: "ZZ",
                name: "ShapitoGram",
                localizedName: nil,
                countryCodes: [shapitoGramCode],
                hidden: false
            )
            countryCodes.append(shapitoGram)
            countryCodesByPrefix["1337"] = (shapitoGram, shapitoGramCode)
        }
    }"""

PHONE_ANCHOR = """public func formatPhoneNumber(_ string: String) -> String {
    do {"""

PHONE_REPLACEMENT = """// ShapitoGram: +1337 plan.
//
// The range is not a calling code, but it starts with "1", so libphonenumber
// parses +1337... as a United States number and prints "+1 (337) 123-3".
// Recognise it before the parser ever sees it.
private func shapitoGramPhoneNumber(_ string: String) -> String? {
    let digits = string.filter { $0 >= "0" && $0 <= "9" }
    guard digits.count > 4, digits.hasPrefix("1337") else {
        return nil
    }
    return "+" + digits
}

public func formatPhoneNumber(_ string: String) -> String {
    // ShapitoGram: +1337 plan.
    if let shapitoGram = shapitoGramPhoneNumber(string) {
        return shapitoGram
    }

    do {"""

CONTEXT_ANCHOR = """public func formatPhoneNumber(context: AccountContext, number: String) -> String {
    if let pattern = lookupPatternByNumber(number, configuration: context.currentCountriesConfiguration.with { $0 }) {"""

CONTEXT_REPLACEMENT = """public func formatPhoneNumber(context: AccountContext, number: String) -> String {
    // ShapitoGram: +1337 plan -- keep the prefix whole instead of letting
    // libphonenumber read it as +1 337.
    if let shapitoGram = shapitoGramPhoneNumber(number) {
        return shapitoGram
    }

    if let pattern = lookupPatternByNumber(number, configuration: context.currentCountriesConfiguration.with { $0 }) {"""


def patch(path, edits):
    if not os.path.isfile(path):
        raise SystemExit(
            "phone plan: file not found: %s\n"
            "  Upstream layout may have changed. Verify with:\n"
            "  https://api.github.com/repos/TelegramMessenger/Telegram-iOS/contents/%s?ref=%s"
            % (path, os.path.basename(path), os.environ.get("UPSTREAM_REF", "<pinned ref>"))
        )

    with open(path, "rb") as f:
        raw = f.read()

    crlf = raw.count(b"\r\n")
    text = raw.decode("utf-8")

    if MARKER in text:
        print("phone plan: %s already patched" % os.path.basename(path))
        return

    for anchor, replacement in edits:
        count = text.count(anchor)
        if count != 1:
            raise SystemExit(
                "phone plan: anchor in %s found %d times, expected exactly 1 -- "
                "upstream changed, fix the anchor:\n%s"
                % (os.path.basename(path), count, anchor)
            )
        text = text.replace(anchor, replacement)

    # Balance check: the replacements above only add whole statement blocks, so
    # the file must stay balanced. A stray brace would otherwise surface as a
    # compile error 40 minutes into the build.
    before = raw.decode("utf-8")
    if (text.count("{") - text.count("}")) != (before.count("{") - before.count("}")):
        raise SystemExit(
            "phone plan: brace balance changed in %s (%d/%d -> %d/%d) -- the "
            "replacement is not self-balanced"
            % (os.path.basename(path),
               before.count("{"), before.count("}"), text.count("{"), text.count("}"))
        )

    out = text.encode("utf-8")
    if crlf:
        out = out.replace(b"\n", b"\r\n")

    with open(path, "wb") as f:
        f.write(out)

    print("phone plan: patched %s (%d -> %d bytes, crlf=%d)"
          % (os.path.basename(path), len(raw), len(out), crlf))


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_shapitogram_phone.py <source_dir>")

    source_dir = sys.argv[1]

    patch(
        os.path.join(source_dir, COUNTRY_TARGET),
        [(SETUP_ANCHOR, SETUP_REPLACEMENT)],
    )
    patch(
        os.path.join(source_dir, PHONE_TARGET),
        [
            (PHONE_ANCHOR, PHONE_REPLACEMENT),
            (CONTEXT_ANCHOR, CONTEXT_REPLACEMENT),
        ],
    )


if __name__ == "__main__":
    main()

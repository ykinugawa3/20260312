package io.github.ykinugawa3.japanguide.i18n

import java.util.Locale

/** Languages the app's UI and translations are available in. */
enum class Lang(val label: String) {
    EN("English"),
    ZH_HANS("简体中文"),
    ZH_HANT("繁體中文"),
    KO("한국어");

    companion object {
        /** Picks the closest supported language for a device locale (English if none match). */
        fun fromLocale(locale: Locale): Lang = when (locale.language) {
            "ko" -> KO
            "zh" -> if (locale.script == "Hant" || locale.country in setOf("TW", "HK", "MO")) ZH_HANT else ZH_HANS
            else -> EN
        }
    }
}

/** A piece of text in every supported language. */
data class L(val en: String, val zhHans: String, val zhHant: String, val ko: String) {
    operator fun get(lang: Lang): String = when (lang) {
        Lang.EN -> en
        Lang.ZH_HANS -> zhHans
        Lang.ZH_HANT -> zhHant
        Lang.KO -> ko
    }

    fun all(): List<String> = listOf(en, zhHans, zhHant, ko)
}

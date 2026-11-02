package io.github.ykinugawa3.japanguide.data

import io.github.ykinugawa3.japanguide.i18n.L
import io.github.ykinugawa3.japanguide.i18n.Lang
import java.math.BigDecimal
import java.util.Locale

/**
 * A foreign currency. [defaultJpyPerUnit] is a rough built-in rate the user is expected to
 * overwrite — the app has no network access by design.
 */
data class Currency(val code: String, val name: L, val defaultJpyPerUnit: Double, val decimals: Int)

object Currencies {
    val all = listOf(
        Currency("USD", L("US dollar", "美元", "美元", "미국 달러"), 150.0, 2),
        Currency("EUR", L("Euro", "欧元", "歐元", "유로"), 175.0, 2),
        Currency("GBP", L("British pound", "英镑", "英鎊", "영국 파운드"), 200.0, 2),
        Currency("CNY", L("Chinese yuan", "人民币", "人民幣", "중국 위안"), 21.0, 2),
        Currency("TWD", L("Taiwan dollar", "新台币", "新台幣", "대만 달러"), 4.8, 0),
        Currency("HKD", L("Hong Kong dollar", "港币", "港幣", "홍콩 달러"), 19.3, 2),
        Currency("KRW", L("Korean won", "韩元", "韓元", "한국 원"), 0.108, 0),
        Currency("THB", L("Thai baht", "泰铢", "泰銖", "태국 바트"), 4.6, 2),
        Currency("SGD", L("Singapore dollar", "新加坡元", "新加坡幣", "싱가포르 달러"), 116.0, 2),
        Currency("AUD", L("Australian dollar", "澳元", "澳幣", "호주 달러"), 98.0, 2),
    )

    fun byCode(code: String): Currency = all.firstOrNull { it.code == code } ?: all.first()

    /** The currency most visitors using [lang] are likely to carry. */
    fun defaultFor(lang: Lang): String = when (lang) {
        Lang.EN -> "USD"
        Lang.ZH_HANS -> "CNY"
        Lang.ZH_HANT -> "TWD"
        Lang.KO -> "KRW"
    }
}

object Converter {
    fun toForeign(jpy: Double, jpyPerUnit: Double): Double = if (jpyPerUnit > 0) jpy / jpyPerUnit else 0.0

    fun toJpy(foreign: Double, jpyPerUnit: Double): Double = foreign * jpyPerUnit

    /** Parses user input such as "1,200" or " 3.5 "; null if it isn't a non-negative number. */
    fun parse(text: String): Double? =
        text.replace(",", "").trim().toDoubleOrNull()?.takeIf { it >= 0 && it.isFinite() }

    /** For editable fields: no grouping separators. */
    fun plain(value: Double, decimals: Int): String = String.format(Locale.US, "%.${decimals}f", value)

    /** For display: with grouping separators. */
    fun pretty(value: Double, decimals: Int): String = String.format(Locale.US, "%,.${decimals}f", value)

    /** A rate without trailing zeros, e.g. 150.0 -> "150", 0.108 -> "0.108". */
    fun rate(value: Double): String = BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()
}

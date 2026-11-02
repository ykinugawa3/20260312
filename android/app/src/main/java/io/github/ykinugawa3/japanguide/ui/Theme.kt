package io.github.ykinugawa3.japanguide.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.intl.LocaleList

private val LightColors = lightColorScheme(
    primary = Color(0xFFBC002D),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFFFDAD9),
    onPrimaryContainer = Color(0xFF40000A),
    secondary = Color(0xFF775656),
    secondaryContainer = Color(0xFFFFDAD9),
    onSecondaryContainer = Color(0xFF2C1515),
    tertiary = Color(0xFF2E5E8C),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFFFB3B3),
    onPrimary = Color(0xFF680016),
    primaryContainer = Color(0xFF920023),
    onPrimaryContainer = Color(0xFFFFDAD9),
    secondary = Color(0xFFE6BDBC),
    secondaryContainer = Color(0xFF5D3F3F),
    onSecondaryContainer = Color(0xFFFFDAD9),
    tertiary = Color(0xFF9DCAFF),
)

@Composable
fun JapanGuideTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}

/**
 * Render with Japanese glyph shapes. Without this, kanji shown on a Chinese- or Korean-language
 * phone use that locale's font variants, which can look wrong to Japanese staff.
 */
fun TextStyle.japanese(): TextStyle = copy(localeList = LocaleList("ja-JP"))

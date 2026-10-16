
package il.fca.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
internal fun UserAvatar(
    name: String,
    size: Dp = 44.dp,
    modifier: Modifier = Modifier
) {
    val dark = isSystemInDarkTheme()

    val background = if (dark) {
        Color(0xFF303941)
    } else {
        Color(0xFFE4E9EC)
    }

    val border = if (dark) {
        Color(0xFF56636E)
    } else {
        Color(0xFFBFC9D0)
    }

    val foreground = if (dark) {
        Color(0xFFF0F3F5)
    } else {
        Color(0xFF243341)
    }

    val initials = avatarInitials(name)

    val fontSize = when {
        size <= 28.dp -> 9.sp
        size <= 36.dp -> 12.sp
        size <= 48.dp -> 16.sp
        else -> 20.sp
    }

    Box(
        modifier = modifier
            .size(size)
            .background(background, CircleShape)
            .border(1.dp, border, CircleShape),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = initials,
            color = foreground,
            fontWeight = FontWeight.ExtraBold,
            fontSize = fontSize,
            lineHeight = fontSize,
            textAlign = TextAlign.Center,
            maxLines = 1,
            softWrap = false
        )
    }
}

internal fun avatarInitials(name: String): String {
    val words = name.trim()
        .split(Regex("\\s+"))
        .filter { it.isNotEmpty() }

    val points = if (words.size > 1) {
        words.take(2)
            .map { it.codePointAt(0) }
            .toIntArray()
    } else {
        words.firstOrNull()
            ?.codePoints()
            ?.limit(2)
            ?.toArray()
            ?: intArrayOf()
    }

    return String(points, 0, points.size)
}

package il.fca.companion.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import il.fca.companion.R

@Composable
internal fun FirstVehicleSetupDialog(dismiss: () -> Unit, setup: () -> Unit) {
    val dark = LocalFcaDark.current
    val wordmarkBlend = if (LocalFcaDark.current) BlendMode.SrcOver else BlendMode.Multiply
    val colors = LocalFcaColors.current
    val windowHeight = with(LocalDensity.current) { LocalWindowInfo.current.containerSize.height.toDp() }
    val maxHeight = (windowHeight - 48.dp).coerceAtLeast(160.dp)
    Dialog(onDismissRequest = dismiss,
        properties = DialogProperties(dismissOnBackPress = true, dismissOnClickOutside = false, usePlatformDefaultWidth = false)) {
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
            Surface(Modifier.padding(horizontal = 24.dp).widthIn(max = 420.dp).fillMaxWidth().heightIn(max = maxHeight),
                shape = RoundedCornerShape(30.dp), shadowElevation = 8.dp,
                color = if (dark) colors.surface else Color(0xFFFFFCF6)) {
                Column(Modifier.verticalScroll(rememberScrollState()).padding(vertical = 18.dp),
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                        // Absolute Left matches the approved control placement in the RTL mockup.
                        IconButton(dismiss, Modifier.align(AbsoluteAlignment.TopLeft).size(44.dp)
                            .background(if (dark) colors.disabled else Color(0xFFF1EEE8), CircleShape)) {
                            CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                                Icon(painterResource(R.drawable.ic_chevron_back), "חזרה", tint = colors.text,
                                    modifier = Modifier.size(22.dp))
                            }
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    Text("שנתחבר?", fontSize = 36.sp, fontWeight = FontWeight.Bold, color = colors.text,
                        textAlign = TextAlign.Center, modifier = Modifier.padding(horizontal = 24.dp))
                    Spacer(Modifier.height(8.dp))
                    Text("זה לוקח דקה והסוכן מחובר לרכב ומעדכן אוטומטית", fontSize = 20.sp,
                        lineHeight = 28.sp, color = colors.text, textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 28.dp))
                    Spacer(Modifier.height(20.dp))
                    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                        Image(painterResource(R.drawable.illustration_companion), null,
                            Modifier.fillMaxWidth().aspectRatio(1672f / 941f), contentScale = ContentScale.Fit)
                    }
                    Spacer(Modifier.height(20.dp))
                    Button(setup, Modifier.padding(horizontal = 32.dp).fillMaxWidth().heightIn(min = 58.dp),
                        shape = RoundedCornerShape(50), colors = ButtonDefaults.buttonColors(
                            containerColor = Color(0xFF112D40), contentColor = Color.White)) {
                        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("להגדרה", fontSize = 22.sp, fontWeight = FontWeight.Bold)
                                Spacer(Modifier.width(16.dp))
                                Icon(painterResource(R.drawable.ic_chevron_right), null, Modifier.size(24.dp))
                            }
                        }
                    }
                    Spacer(Modifier.height(22.dp))
                    Image(painterResource(if (LocalFcaDark.current) R.drawable.family_car_agent_road_logo_1__dark else R.drawable.fca_header_wordmark),
                        "Family Car Agent", Modifier.width(180.dp).height(44.dp).graphicsLayer {
                            compositingStrategy = CompositingStrategy.Offscreen
                            blendMode = wordmarkBlend
                        }, contentScale = ContentScale.Fit,
                        alpha = .55f)
                    Spacer(Modifier.height(4.dp))
                }
            }
        }
    }
}

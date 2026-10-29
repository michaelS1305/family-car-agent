package il.fca.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R

private val Navy: Color
    @Composable get() = fcaColor(Color(0xFF112642), FcaColorRole.TEXT)
private val Primary: Color
    @Composable get() = fcaColor(Color(0xFF243341), FcaColorRole.TEXT)
private val Secondary: Color
    @Composable get() = fcaColor(Color(0xFF637B97), FcaColorRole.SECONDARY)
private val Outline: Color
    @Composable get() = fcaColor(Color(0xFFD7D9DC), FcaColorRole.BORDER)
private val Shape = RoundedCornerShape(16.dp)
private const val ADDRESS_HELP = "אפשר להזין עיר, רחוב ומספר בית גם ללא פסיקים.\nבשלב הבא יש לבדוק ולאשר את הכתובת שנמצאה."
internal const val DRIVING_CONSENT = "אני עומד/ת בדרישות החוק החלות על נהג פעיל ברכב זה. בישראל, ההנחה למוצר היא גיל מינימלי של 16 שנים ו־9 חודשים לרישיון B. אם אני קטין/ה, השימוש הוא באחריות ובאישור הורה או אפוטרופוס. ידוע לי שהאפליקציה אינה בודקת תוקף רישיון או כשירות חוקית לנהיגה."

@Composable
internal fun EntryUi(model: OnboardingModel, chat: ChatViewModel, history: HistoryViewModel, vehicles: VehiclesViewModel, family: FamilyViewModel,
            booking: BookingViewModel,
            login: () -> Unit, next: () -> Unit,
            back: () -> Unit, changeAddress: () -> Unit, retryBootstrap: () -> Unit, enteredApp: () -> Unit,
            logout: () -> Unit, account: AccountSettingsModel? = null,
            firstVehicleSetup: FirstVehicleSetupState? = null, setupIdentity: () -> VehiclesIdentity? = { null }) {
    SideEffect {
        account?.reconcile()
        history.reconcileIdentity()
        vehicles.reconcileIdentity()
        family.reconcileIdentity()
    }
    var legal by remember { mutableStateOf<LegalCopy?>(null) }
    LaunchedEffect(chat.ownerGeneration, model.authenticatedFamilyId, model.screen) {
        booking.activate(chat.ownerGeneration, model.authenticatedFamilyId)
    }
    FcaTheme {
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
            BackHandler(model.screen == EntryScreen.LOGIN || model.screen == EntryScreen.ONBOARDING || model.busy) { back() }
            if (model.screen == EntryScreen.AUTHENTICATED_APP) LaunchedEffect(Unit) { enteredApp() }
            Surface(Modifier.fillMaxSize()) {
                Box(Modifier.fillMaxSize()) {
                if (model.screen == EntryScreen.AUTHENTICATED_APP) {
                    LaunchedEffect(chat.ownerGeneration) { chat.enter() }
                    key(chat.ownerGeneration) {
                        AuthenticatedAppShell(chat, model.authenticatedName, logout, model.busy, model.error,
                            history, model.authenticatedFamilyId, vehicles, family, booking, account,
                            firstVehicleSetup, setupIdentity())
                    }
                    account?.let { AccountDeletionDialog(it, logout, model.busy, model.error) }
                } else if (model.screen == EntryScreen.BOOTSTRAP) {
                    if (!model.busy) {
                        FcaErrorScreen("יש בעיה, נסה שוב", retry = retryBootstrap)
                    }
                } else if (model.screen == EntryScreen.INTRO) {
                    Column(Modifier.fillMaxSize().safeDrawingPadding(), horizontalAlignment = Alignment.CenterHorizontally) {
                        IntroScreen(Modifier.weight(1f), !model.busy) { model.select(it) }
                        Column(Modifier.widthIn(max = 440.dp).fillMaxWidth().padding(horizontal = 20.dp)) { Feedback(model) }
                    }
                } else if (model.screen == EntryScreen.LOGIN) {
                    Column(Modifier.fillMaxSize().safeDrawingPadding(), horizontalAlignment = Alignment.CenterHorizontally) {
                        GoogleLoginScreen(Modifier.weight(1f), !model.busy, login, back) { legal = it }
                        Column(Modifier.widthIn(max = 440.dp).fillMaxWidth().padding(horizontal = 16.dp)) { Feedback(model) }
                    }
                } else {
                BoxWithConstraints(Modifier.safeDrawingPadding().imePadding().fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                    val viewport = maxHeight
                    val onboarding = model.screen == EntryScreen.ONBOARDING
                    val compact = viewport < 620.dp
                    val bodyModifier = if (onboarding) Modifier.fillMaxHeight() else
                        Modifier.verticalScroll(rememberScrollState()).heightIn(min = viewport)
                    Column(Modifier.widthIn(max = 440.dp).fillMaxWidth().then(bodyModifier)
                        .padding(horizontal = if (onboarding) 16.dp else 24.dp, vertical = if (onboarding) 12.dp else 18.dp),
                        horizontalAlignment = Alignment.CenterHorizontally) {
                        when (model.screen) {
                            EntryScreen.INTRO -> Unit // Rendered separately without a scrolling ancestor.
                            EntryScreen.LOGIN -> Unit // Separate fixed-viewport login layout.
                            EntryScreen.ONBOARDING -> {
                                Header(model.step.toString() + " מתוך " + model.totalSteps, !model.busy, back)
                                Gap(if (compact) 12 else if (model.step == 3) 24 else 48)
                                when {
                                    model.step == 1 -> {
                                        StepHeading("איך קוראים למשפחה?"); Gap(if (compact) 24 else 52)
                                        Field("שם המשפחה", "לדוגמה: כהן", model.familyName, !model.busy) { model.familyName = it }
                                    }
                                    model.step == 2 -> {
                                        StepHeading("מה כתובת הבית?"); Gap(if (compact) 10 else 16)
                                        StepSupporting("הכתובת נדרשת לאימות המשפחה ולבדיקת ניתוק הרכב האופציונלית בקרבת הבית."); Gap(if (compact) 16 else 30)
                                        Field("כתובת הבית", "תל אביב, דיזנגוף, 120", model.address, !model.busy) { model.address = it }
                                        Gap(8); StepSupporting(ADDRESS_HELP, helper = true)
                                    }
                                    model.step == 3 -> {
                                        StepHeading("זו הכתובת הנכונה?"); Gap(10)
                                        StepSupporting("בדקו את הפרטים לפני שממשיכים."); Gap(if (compact) 12 else 20)
                                        OutlinedCard(Modifier.fillMaxWidth(), shape = Shape, border = BorderStroke(1.dp, Outline),
                                            colors = CardDefaults.outlinedCardColors(containerColor = fcaColor(Color.White, FcaColorRole.SURFACE))) {
                                            Text(model.resolvedAddress, Modifier.fillMaxWidth().padding(12.dp),
                                                textAlign = TextAlign.Center, fontWeight = FontWeight.SemiBold)
                                        }
                                        Gap(10)
                                        VerifiedAddressMap(model.addressLocation,
                                            Modifier.fillMaxWidth().height(if (compact) 150.dp else 180.dp))
                                    }
                                    model.step == 4 && model.route == LoginRoute.JOIN_FAMILY -> {
                                        StepHeading("קוד המשפחה"); Gap(if (compact) 24 else 46)
                                        Field("קוד המשפחה", "", model.joinCode, !model.busy, KeyboardType.Ascii) { model.joinCode = it }
                                        Gap(12); StepSupporting("שימו לב, יש מספר ניסיונות מוגבל", helper = true)
                                    }
                                    else -> {
                                        StepHeading("איך קוראים לך?"); Gap(if (compact) 16 else 24)
                                        Field("השם שלך", "הקלד את שמך", model.userName, !model.busy) { model.userName = it }; Gap(10)
                                        OutlinedCard(Modifier.fillMaxWidth(), shape = Shape, border = BorderStroke(1.dp, Outline),
                                            colors = CardDefaults.outlinedCardColors(containerColor = fcaColor(Color.White, FcaColorRole.SURFACE))) {
                                            Row(Modifier.padding(4.dp), verticalAlignment = Alignment.Top) {
                                                Checkbox(model.consent, { model.consent = it }, enabled = !model.busy,
                                                    modifier = Modifier.semantics { contentDescription = DRIVING_CONSENT })
                                                Text(DRIVING_CONSENT, Modifier.weight(1f).padding(top = 4.dp, bottom = 4.dp, end = 4.dp),
                                                    fontSize = 11.sp, lineHeight = 15.sp, color = Secondary)
                                            }
                                        }
                                    }
                                }
                                Spacer(Modifier.weight(1f))
                                Feedback(model)
                                Action(when {
                                    model.step == 3 -> "כן, המשך"
                                    model.step == model.totalSteps && model.route == LoginRoute.CREATE_FAMILY -> "יצירת המשפחה"
                                    model.step == model.totalSteps -> "הצטרפות למשפחה"
                                    else -> "המשך"
                                }, !model.busy, next)
                                if (model.step == 3) {
                                    Gap(10)
                                    OutlinedButton(onClick = changeAddress, enabled = !model.busy, shape = Shape,
                                        modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
                                        border = BorderStroke(1.dp, Outline)) { Text("שנה כתובת", fontWeight = FontWeight.SemiBold) }
                                }
                            }
                            EntryScreen.SUCCESS -> {
                                Gap(60); Logo(100); Gap(26)
                                Heading(if (model.route == LoginRoute.CREATE_FAMILY) "המשפחה נוצרה בהצלחה" else "הצטרפת למשפחה בהצלחה")
                                if (model.route == LoginRoute.CREATE_FAMILY) {
                                    Gap(24); Supporting("קוד המשפחה:")
                                    Text(model.createdCode, fontSize = 30.sp, fontWeight = FontWeight.Bold)
                                }
                                Spacer(Modifier.weight(1f).heightIn(min = 40.dp))
                                Action("המשך", !model.busy, next)
                            }
                            EntryScreen.AUTHENTICATED_APP, EntryScreen.BOOTSTRAP -> Unit
                        }
                        if (model.screen != EntryScreen.ONBOARDING) Feedback(model)
                    }
                }
            }
                    FcaLoadingOverlay(bootstrapLoading(model.screen, model.busy))
                }
            }
            legal?.let { document ->
                AlertDialog(onDismissRequest = { legal = null }, title = { Text(document.title) },
                    text = { Text(document.body, Modifier.verticalScroll(rememberScrollState())) },
                    confirmButton = { TextButton(onClick = { legal = null }) { Text("סגירה") } })
            }
        }
    }
}

@Composable private fun Gap(height: Int) { Spacer(Modifier.height(height.dp)) }
@Composable private fun Header(title: String, enabled: Boolean, back: () -> Unit) {
    Box(Modifier.fillMaxWidth().heightIn(min = 48.dp), contentAlignment = Alignment.Center) {
        Text(title, color = Secondary, fontSize = 16.sp, modifier = Modifier.padding(horizontal = 52.dp))
        OutlinedIconButton(onClick = back, enabled = enabled, shape = RoundedCornerShape(13.dp), border = BorderStroke(1.dp, Outline),
            modifier = Modifier.align(Alignment.CenterStart).size(48.dp).semantics { contentDescription = "חזרה" }) {
            Text("→", fontSize = 25.sp, color = Navy)
        }
    }
}
@Composable private fun Logo(size: Int) {
    Image(painterResource(R.drawable.fca_logo), null, Modifier.size(size.dp), contentScale = ContentScale.Fit)
}
@Composable private fun Heading(text: String) {
    Text(text, Modifier.fillMaxWidth(), fontSize = 27.sp, lineHeight = 34.sp,
        fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, color = Navy)
}
@Composable private fun StepHeading(text: String) {
    Text(text, Modifier.fillMaxWidth(), fontSize = 30.sp, lineHeight = 38.sp,
        fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, color = Navy)
}
@Composable private fun StepSupporting(text: String, helper: Boolean = false) {
    Text(text, Modifier.fillMaxWidth(), fontSize = if (helper) 13.sp else 14.sp,
        lineHeight = if (helper) 19.sp else 21.sp, textAlign = TextAlign.Center, color = Secondary)
}
@Composable private fun Supporting(text: String, small: Boolean = false) {
    Text(text, Modifier.fillMaxWidth(), fontSize = if (small) 14.sp else 16.sp,
        lineHeight = if (small) 22.sp else 25.sp, textAlign = TextAlign.Center, color = Secondary)
}
@Composable private fun Action(text: String, enabled: Boolean, action: () -> Unit) {
    Button(onClick = action, enabled = enabled, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp),
        shape = Shape, colors = ButtonDefaults.buttonColors(containerColor = Primary, contentColor = fcaColor(Color.White, FcaColorRole.ON_ACTION))) {
        Text(text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
    }
}
@Composable private fun Field(label: String, placeholder: String, value: String, enabled: Boolean,
                              keyboard: KeyboardType = KeyboardType.Text, change: (String) -> Unit) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Text(label, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
        OutlinedTextField(value, change, placeholder = { Text(placeholder, color = fcaColor(Color(0xFF96A3B5), FcaColorRole.SECONDARY)) },
            enabled = enabled, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = keyboard),
            modifier = Modifier.fillMaxWidth().semantics { contentDescription = label }, shape = Shape,
            colors = OutlinedTextFieldDefaults.colors(unfocusedBorderColor = Outline, focusedBorderColor = Primary,
                unfocusedContainerColor = fcaColor(Color.White, FcaColorRole.SURFACE), focusedContainerColor = fcaColor(Color.White, FcaColorRole.SURFACE)))
    }
}
@Composable private fun Feedback(model: OnboardingModel) {
    if (model.busy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Gap(12) }
    model.error?.let { Text(it, Modifier.fillMaxWidth().padding(bottom = 10.dp),
        color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
    model.failure?.let { failure ->
        failure.attemptsRemaining?.let { Text("ניסיונות שנותרו: $it", fontSize = 13.sp, color = Secondary) }
        failure.retryAfterSeconds?.let { Text("ניתן לנסות שוב בעוד $it שניות", fontSize = 13.sp, color = Secondary) }
    }
}

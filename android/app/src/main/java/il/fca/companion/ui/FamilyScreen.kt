package il.fca.companion.ui

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.os.PersistableBundle
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*
import il.fca.companion.R
import il.fca.companion.net.*
import kotlinx.coroutines.delay

internal fun familyInitials(name: String): String {
    val words = name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }

    val points =
        if (words.size > 1) {
            words.take(2).map { it.codePointAt(0) }.toIntArray()
        } else {
            words.firstOrNull()
                ?.codePoints()
                ?.limit(2)
                ?.toArray()
                ?: intArrayOf()
        }

    return String(points, 0, points.size)
}

@Composable
internal fun FamilyScreen(
    model: FamilyViewModel,
    familyId: Long?,
    back: () -> Unit
) {
    DisposableEffect(model, familyId) {
        model.start()

        onDispose {
            model.stop()
        }
    }

    BackHandler(onBack = back)

    val state = model.visibleState

    CompositionLocalProvider(
        LocalLayoutDirection provides LayoutDirection.Rtl
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .background(Color(0xFFF6F7F7))
                .navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            VehicleProductHeader(back)

            Column(
                Modifier
                    .widthIn(max = 620.dp)
                    .fillMaxWidth()
                    .weight(1f)
                    .verticalScroll(rememberScrollState())
                    .padding(
                        horizontal = 18.dp,
                        vertical = 10.dp
                    ),
                verticalArrangement = Arrangement.spacedBy(18.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(108.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Image(
                        painter = painterResource(R.drawable.family_icon),
                        contentDescription = "משפחה",
                        modifier = Modifier
                            .requiredSize(200.dp)
                            .offset(y = (-15).dp),
                        contentScale = ContentScale.Fit
                    )
                }

                val profile = state.profile

                when {
                    state.loading -> {
                        CircularProgressIndicator(
                            Modifier.padding(24.dp)
                        )

                        Text(
                            "טוען…",
                            color = VehicleInk
                        )
                    }

                    state.loadError || profile == null -> {
                        Text(
                            "לא ניתן לטעון את פרטי המשפחה",
                            color = VehicleInk
                        )

                        TextButton(model::retry) {
                            Text("נסה שוב")
                        }
                    }

                    else -> {
                        VehiclePanel {
                            Row(
                                Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    "אנשי המשפחה",
                                    modifier = Modifier.weight(1f),
                                    color = VehicleInk,
                                    fontSize = 18.sp,
                                    fontWeight = FontWeight.Bold
                                )

                                // Deliberately inert V1 placeholder:
                                // no invitation or feedback action.
                                FamilyIconAction(
                                    R.drawable.ic_add,
                                    "הוספה",
                                    {}
                                )
                            }

                            profile.members.forEach { member ->
                                key(member.ref) {
                                    FamilyMemberCard(
                                        member = member,
                                        canManage = profile.canManage,
                                        pending = member.ref in state.rolePending,
                                        failed = member.ref in state.roleErrors
                                    ) {
                                        model.role(member.ref, it)
                                    }
                                }
                            }
                        }

                        FamilyAddress(
                            model,
                            state,
                            profile
                        )

                        FamilyCode(
                            model,
                            state,
                            profile
                        )
                    }
                }
            }
        }

        if (
            state.codeConfirmation &&
            state.profile?.canManage == true
        ) {
            AlertDialog(
                onDismissRequest = model::cancelRegenerate,
                text = {
                    Column(
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            "הקוד הישן יפסיק לעבוד. ליצור קוד חדש?"
                        )

                        if (state.codeError) {
                            Text(
                                "לא ניתן לאשר יצירת קוד חדש. נסו שוב.",
                                color = MaterialTheme.colorScheme.error
                            )
                        }
                    }
                },
                confirmButton = {
                    TextButton(
                        model::regenerate,
                        enabled = !state.codePending
                    ) {
                        Text(
                            if (state.codePending) {
                                "ממתינים…"
                            } else {
                                "אשר"
                            }
                        )
                    }
                },
                dismissButton = {
                    TextButton(
                        model::cancelRegenerate,
                        enabled = !state.codePending
                    ) {
                        Text("ביטול")
                    }
                }
            )
        }
    }
}

@Composable
private fun FamilyIconAction(
    asset: Int,
    description: String,
    click: () -> Unit,
    enabled: Boolean = true
) {
    IconButton(
        onClick = click,
        enabled = enabled,
        modifier = Modifier
            .size(48.dp)
            .background(
                Color(0xFFF1F5F9),
                CircleShape
            )
    ) {
        Image(
            painter = painterResource(asset),
            contentDescription = description,
            modifier = Modifier.size(24.dp)
        )
    }
}

@Composable
private fun FamilyMemberCard(
    member: FamilyMember,
    canManage: Boolean,
    pending: Boolean,
    failed: Boolean,
    select: (FamilyRole) -> Unit
) {
    var expanded by remember(member.ref) {
        mutableStateOf(false)
    }

    Column(
        Modifier
            .fillMaxWidth()
            .background(
                Color.White.copy(alpha = .85f),
                RoundedCornerShape(18.dp)
            )
            .border(
                1.dp,
                VehicleBorder,
                RoundedCornerShape(18.dp)
            )
            .padding(10.dp)
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 60.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(9.dp)
        ) {
            Box(
                Modifier
                    .size(44.dp)
                    .background(
                        Color(0xFFE5EFF9),
                        CircleShape
                    ),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    familyInitials(member.name),
                    color = VehicleInk,
                    fontWeight = FontWeight.Bold,
                    fontSize = 17.sp
                )
            }

            Column(
                Modifier.weight(1f)
            ) {
                Text(
                    member.name,
                    color = VehicleInk,
                    fontWeight = FontWeight.Bold,
                    fontSize = 17.sp
                )

                if (member.admin) {
                    Text(
                        "מנהל המשפחה",
                        color = Color(0xFF637B97),
                        fontSize = 12.sp
                    )
                }
            }

            if (canManage) {
                Box {
                    OutlinedButton(
                        onClick = {
                            expanded = true
                        },
                        enabled = !pending,
                        contentPadding = PaddingValues(
                            horizontal = 5.dp,
                            vertical = 1.dp
                        ),
                        shape = RoundedCornerShape(11.dp),
                        modifier = Modifier.widthIn(max = 88.dp)
                    ) {
                        Text(
                            if (pending) {
                                "מעדכן…"
                            } else {
                                member.role.label
                            },
                            fontSize = 8.sp,
                            color = VehicleInk
                        )

                        Text(
                            " ▾",
                            fontSize = 11.sp,
                            color = VehicleInk
                        )
                    }

                    DropdownMenu(
                        expanded = expanded && !pending,
                        onDismissRequest = {
                            expanded = false
                        }
                    ) {
                        FamilyRole.entries.forEach { role ->
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        role.label,
                                        fontSize = 13.sp
                                    )
                                },
                                onClick = {
                                    expanded = false
                                    select(role)
                                }
                            )
                        }
                    }
                }
            } else {
                Text(
                    member.role.label,
                    color = VehicleInk,
                    fontSize = 12.sp,
                    modifier = Modifier.widthIn(max = 95.dp)
                )
            }
        }

        if (failed) {
            Text(
                "התפקיד לא עודכן. נסו שוב.",
                color = MaterialTheme.colorScheme.error,
                fontSize = 12.sp
            )
        }
    }
}

@Composable
private fun FamilyAddress(
    model: FamilyViewModel,
    state: FamilyState,
    profile: FamilyProfile
) {
    VehiclePanel {
        Text(
            "כתובת",
            color = VehicleInk,
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold
        )

        if (state.addressStage == AddressStage.VIEW) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .border(
                        1.dp,
                        VehicleBorder,
                        RoundedCornerShape(18.dp)
                    )
                    .padding(12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    profile.address,
                    Modifier.weight(1f),
                    color = VehicleInk,
                    fontSize = 16.sp
                )

                if (profile.canManage) {
                    FamilyIconAction(
                        R.drawable.ic_edit,
                        "עריכת כתובת",
                        model::editAddress
                    )
                }
            }
        } else if (
            state.addressStage == AddressStage.EDIT ||
            state.addressStage == AddressStage.VERIFYING
        ) {
            OutlinedTextField(
                value = state.draft,
                onValueChange = model::draft,
                enabled = !state.addressBusy,
                modifier = Modifier.fillMaxWidth(),
                label = {
                    Text("כתובת הבית")
                }
            )

            Row {
                TextButton(
                    model::verifyAddress,
                    enabled = !state.addressBusy
                ) {
                    Text(
                        if (state.addressBusy) {
                            "בודק…"
                        } else {
                            "אשר"
                        }
                    )
                }

                TextButton(
                    model::cancelAddress,
                    enabled = !state.addressBusy
                ) {
                    Text("ביטול")
                }
            }
        } else {
            Column(
                Modifier
                    .fillMaxWidth()
                    .border(
                        1.dp,
                        VehicleBorder,
                        RoundedCornerShape(16.dp)
                    )
                    .padding(12.dp)
            ) {
                Text(
                    "זו הכתובת הנכונה?",
                    color = VehicleInk,
                    fontWeight = FontWeight.Bold
                )

                Text(
                    state.candidate?.display.orEmpty(),
                    color = VehicleInk
                )

                Row {
                    TextButton(
                        model::confirmAddress,
                        enabled = !state.addressBusy
                    ) {
                        Text(
                            if (state.addressBusy) {
                                "ממתינים…"
                            } else {
                                "אשר"
                            }
                        )
                    }

                    TextButton(
                        model::reviseAddress,
                        enabled = !state.addressBusy
                    ) {
                        Text("שנה כתובת")
                    }

                    TextButton(
                        model::cancelAddress,
                        enabled = !state.addressBusy
                    ) {
                        Text("ביטול")
                    }
                }
            }
        }

        state.addressError?.let {
            Text(
                it,
                color = MaterialTheme.colorScheme.error,
                fontSize = 13.sp
            )
        }
    }
}

@Composable
private fun FamilyCode(
    model: FamilyViewModel,
    state: FamilyState,
    profile: FamilyProfile
) {
    val context = LocalContext.current

    var feedback by remember(profile.code) {
        mutableStateOf<String?>(null)
    }

    LaunchedEffect(feedback) {
        if (feedback != null) {
            delay(2500)
            feedback = null
        }
    }

    VehiclePanel {
        Text(
            "קוד משפחתי",
            color = VehicleInk,
            fontSize = 21.sp,
            fontWeight = FontWeight.Bold
        )

        Column(
            Modifier
                .fillMaxWidth()
                .border(
                    1.dp,
                    VehicleBorder,
                    RoundedCornerShape(18.dp)
                )
                .padding(12.dp)
        ) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                CompositionLocalProvider(
                    LocalLayoutDirection provides LayoutDirection.Ltr
                ) {
                    Text(
                        profile.code,
                        Modifier.weight(1f),
                        color = VehicleInk,
                        fontSize = 30.sp,
                        letterSpacing = 4.sp,
                        fontWeight = FontWeight.Bold
                    )
                }

                Spacer(
                    Modifier.width(8.dp)
                )

                FamilyIconAction(
                    R.drawable.ic_copy,
                    "העתקת קוד משפחתי",
                    {
                        model.visibleState.profile?.code?.let { code ->
                            feedback =
                                try {
                                    val clip =
                                        ClipData.newPlainText(
                                            "קוד משפחתי",
                                            code
                                        )

                                    clip.description.extras =
                                        PersistableBundle().apply {
                                            putBoolean(
                                                ClipDescription.EXTRA_IS_SENSITIVE,
                                                true
                                            )
                                        }

                                    context
                                        .getSystemService(
                                            ClipboardManager::class.java
                                        )
                                        .setPrimaryClip(clip)

                                    "הקוד הועתק"
                                } catch (_: Exception) {
                                    "לא ניתן להעתיק כרגע"
                                }
                        }
                    }
                )
            }

            feedback?.let {
                Text(
                    it,
                    color = VehicleInk,
                    fontSize = 13.sp
                )
            }

            if (profile.canManage) {
                HorizontalDivider(
                    Modifier.padding(vertical = 10.dp),
                    color = VehicleBorder
                )

                OutlinedButton(
                    model::askRegenerate,
                    enabled = !state.codePending,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("יצירת קוד חדש")
                }
            }

            if (
                state.codeError &&
                !state.codeConfirmation
            ) {
                Text(
                    "לא ניתן לאשר יצירת קוד חדש.",
                    color = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}
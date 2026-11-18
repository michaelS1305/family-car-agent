package il.fca.companion

import il.fca.companion.ui.*
import il.fca.companion.net.*
import org.junit.Assert.*
import org.junit.Test
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth

class BookingViewModelTest {
    private val today = LocalDate.of(2026, 10, 15)
    private fun model() = BookingViewModel(object : BookingGateway {
        override suspend fun reservations(owner: String, range: BookingRange): List<BookingReservation> =
            error("Calendar-only test must not request data")
    }, { BookingIdentity("owner", 2) }, today = { today })

    @Test fun initializesAndRetainsStateForSameIdentity() {
        val model = model()
        assertEquals(today, model.selectedDate)
        assertEquals(YearMonth.of(2026, 10), model.visibleMonth)
        model.activate(1, 2)
        model.nextMonth()
        model.activate(1, 2)
        assertEquals(YearMonth.of(2026, 11), model.visibleMonth)
        model.activate(2, 2)
        assertEquals(today, model.selectedDate)
    }

    @Test fun rectangularSundayFirstFiveAndSixWeeks() {
        for ((month, count) in listOf(YearMonth.of(2026, 4) to 35, YearMonth.of(2026, 5) to 42)) {
            val days = bookingMonthDays(month)
            assertEquals(count, days.size)
            assertEquals(DayOfWeek.SUNDAY, days.first().dayOfWeek)
            assertEquals(DayOfWeek.SATURDAY, days.last().dayOfWeek)
            days.zipWithNext().forEach { (a, b) -> assertEquals(a.plusDays(1), b) }
            assertEquals(days, bookingMonthDays(month))
            assertEquals(month.lengthOfMonth(), days.count { YearMonth.from(it) == month })
        }
        assertEquals(LocalDate.of(2026, 3, 29), bookingMonthDays(YearMonth.of(2026, 4)).first())
        assertEquals(LocalDate.of(2026, 5, 2), bookingMonthDays(YearMonth.of(2026, 4)).last())
    }

    @Test fun selectionAdjacentMonthsAndYearBoundaries() {
        val model = model()
        model.selectDate(LocalDate.of(2026, 12, 31))
        assertEquals(YearMonth.of(2026, 12), model.visibleMonth)
        model.nextMonth()
        assertEquals(LocalDate.of(2027, 1, 31), model.selectedDate)
        model.previousMonth()
        assertEquals(LocalDate.of(2026, 12, 31), model.selectedDate)
        model.selectDate(LocalDate.of(2027, 1, 1))
        assertEquals(LocalDate.of(2027, 1, 1), model.selectedDate)
        assertEquals(YearMonth.of(2027, 1), model.visibleMonth)
    }

    @Test fun leapFebruaryAndShortMonthSelection() {
        val month = YearMonth.of(2028, 2)
        assertTrue(bookingMonthDays(month).contains(LocalDate.of(2028, 2, 29)))
        val model = model()
        model.selectDate(LocalDate.of(2028, 1, 31))
        model.nextMonth()
        assertEquals(LocalDate.of(2028, 2, 29), model.selectedDate)
    }

    @Test fun finitePagesAndWeekdayPositions() {
        val model = model()
        assertEquals(60, model.pageOf(model.visibleMonth))
        model.moveToMonth(model.firstMonth)
        model.previousMonth()
        assertEquals(model.firstMonth, model.visibleMonth)
        model.moveToMonth(model.monthAt(120))
        model.nextMonth()
        assertEquals(model.monthAt(120), model.visibleMonth)
        for (month in 1..12) bookingMonthDays(YearMonth.of(2026, month)).forEachIndexed { index, date ->
            assertEquals(index % 7, date.dayOfWeek.value % 7)
        }
    }
}

package il.fca.companion.ui

import il.fca.companion.net.BookingRange
import il.fca.companion.net.BookingReservation
import il.fca.companion.net.BookingQuery
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter

internal fun bookingRange(month: YearMonth): BookingRange = bookingMonthDays(month).let {
    BookingRange(it.first(), it.last().plusDays(1))
}
internal fun BookingReservation.overlaps(date: LocalDate) =
    start.isBefore(date.plusDays(1).atStartOfDay()) && end.isAfter(date.atStartOfDay())

internal fun bookingRows(rows: List<BookingReservation>, date: LocalDate) = rows.filter { it.overlaps(date) }
    .sortedWith(compareByDescending<BookingReservation> { it.start }.thenBy { it.ref })

internal fun bookingDots(rows: List<BookingReservation>, range: BookingRange): Set<LocalDate> =
    generateSequence(range.start) { it.plusDays(1) }.takeWhile { it < range.endExclusive }
        .filter { date -> rows.any { it.overlaps(date) } }.toSet()

internal fun bookingRows(rows: List<BookingReservation>, date: LocalDate, query: BookingQuery): List<BookingReservation> {
    val interval = query.effective ?: return emptyList()
    val start = maxOf(date.atStartOfDay(), interval.start)
    val end = minOf(date.plusDays(1).atStartOfDay(), interval.end)
    if (start >= end) return emptyList()
    return rows.filter { query.filters.matches(it) && it.start < end && it.end > start }
        .sortedWith(compareByDescending<BookingReservation> { it.start }.thenBy { it.ref })
}

internal fun bookingDots(rows: List<BookingReservation>, query: BookingQuery): Set<LocalDate> =
    generateSequence(query.grid.start) { it.plusDays(1) }.takeWhile { it < query.grid.endExclusive }
        .filter { bookingRows(rows, it, query).isNotEmpty() }.toSet()

internal fun bookingTimeLabel(row: BookingReservation): String {
    val pattern = if (row.start.toLocalDate() == row.end.toLocalDate()) "HH:mm"
        else if (row.start.year == row.end.year) "dd.MM HH:mm" else "dd.MM.uuuu HH:mm"
    val format = DateTimeFormatter.ofPattern(pattern)
    return "${row.start.format(format)} – ${row.end.format(format)}"
}

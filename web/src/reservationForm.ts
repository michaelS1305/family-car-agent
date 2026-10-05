export type ReservationFormValue = {
  startDate: string
  startTime: string
  endDate: string
  endTime: string
}

type Interval = { start_time: string; end_time: string }

export function reservationFormValue(reservation?: Interval): ReservationFormValue {
  const start = reservation?.start_time ?? ''
  const end = reservation?.end_time ?? ''
  return {
    startDate: start.slice(0, 10),
    startTime: start.slice(11, 19),
    endDate: end.slice(0, 10),
    endTime: end.slice(11, 19),
  }
}

export function intervalFromForm(form: ReservationFormValue): Interval {
  const time = (value: string) => value.length === 5 ? `${value}:00` : value
  return {
    start_time: `${form.startDate}T${time(form.startTime)}`,
    end_time: `${form.endDate}T${time(form.endTime)}`,
  }
}

const DATE = new Intl.DateTimeFormat('he-IL', {
  weekday: 'short', day: 'numeric', month: 'long', year: 'numeric',
})
const TIME = new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' })

export function reservationPresentation(reservation: Interval) {
  const start = new Date(reservation.start_time)
  const end = new Date(reservation.end_time)
  const sameDay = start.getFullYear() === end.getFullYear()
    && start.getMonth() === end.getMonth() && start.getDate() === end.getDate()
  return {
    title: DATE.format(start),
    interval: sameDay
      ? `${TIME.format(start)}–${TIME.format(end)}`
      : `${DATE.format(start)} ${TIME.format(start)} — ${DATE.format(end)} ${TIME.format(end)}`,
    sameDay,
  }
}

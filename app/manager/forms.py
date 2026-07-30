"""WTForms classes for manager CRUD."""
from flask_wtf import FlaskForm
from wtforms import (StringField, IntegerField, SubmitField,
                     SelectField, TextAreaField, TimeField,
                     FieldList, FormField, BooleanField, DateField, FloatField)
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class ContactForm(FlaskForm):
    class Meta:
        csrf = False

    name = StringField("Name", validators=[Optional(), Length(max=120)])
    phone = StringField("Phone", validators=[Optional(), Length(max=40)])


class StopForm(FlaskForm):
    name = StringField("Customer Name", validators=[DataRequired(), Length(max=120)])
    address = StringField("Address", validators=[Optional(), Length(max=255)])
    latitude = FloatField(
        "Latitude",
        validators=[Optional()],
        description="Auto-filled by geocoding. Override manually if wrong.",
    )
    longitude = FloatField(
        "Longitude",
        validators=[Optional()],
        description="Auto-filled by geocoding. Override manually if wrong.",
    )
    service_type = SelectField(
        "Service Type",
        choices=[
            ("", "— select —"),
            ("mats", "Mats"),
            ("uniforms", "Uniforms"),
            ("restrooms", "Restrooms"),
            ("chemical", "Chemical"),
            ("cleaning_supplies", "Cleaning Supplies"),
            ("mixed", "Mixed"),
        ],
        validators=[Optional()],
    )
    service_time_solo_minutes = IntegerField(
        "Solo Service Time (minutes)",
        validators=[DataRequired(), NumberRange(min=1)],
        default=15,
    )
    open_time = TimeField("Opens", validators=[Optional()])
    close_time = TimeField("Closes", validators=[Optional()])
    volume_units = IntegerField(
        "Volume (units)",
        validators=[DataRequired(), NumberRange(min=0)],
        default=0,
    )
    special_instructions = TextAreaField(
        "Special Instructions",
        description="Gate codes, check-in requirements, etc.",
        validators=[Optional()],
    )
    contacts = FieldList(FormField(ContactForm), min_entries=1, max_entries=10)
    submit = SubmitField("Save Stop")


class RouteForm(FlaskForm):
    name = StringField("Route Name", validators=[DataRequired(), Length(max=120)])
    assigned_ssr_id = SelectField("Assigned SSR", coerce=int, validators=[Optional()])
    truck_capacity_volume = IntegerField(
        "Truck Capacity (units)",
        validators=[DataRequired(), NumberRange(min=1)],
        default=200,
    )
    submit = SubmitField("Save Route")


class RouteStopForm(FlaskForm):
    stop_id = SelectField("Stop", coerce=int, validators=[DataRequired()])
    service_days = StringField(
        "Service Days",
        validators=[DataRequired(), Length(max=20)],
        description="e.g. MWF or TR or MTWRF",
    )
    volume_override = IntegerField(
        "Volume Override (leave blank to use stop default)",
        validators=[Optional(), NumberRange(min=0)],
    )
    submit = SubmitField("Add Stop to Route")


class HolidayForm(FlaskForm):
    name = StringField("Holiday Name", validators=[DataRequired(), Length(max=120)])
    date = DateField("Date", validators=[DataRequired()])
    plant_closed = BooleanField(
        "Plant Closed",
        description="If checked, no routes run this day.",
        default=True,
    )
    submit = SubmitField("Save Holiday")


class StopClosureForm(FlaskForm):
    stop_id = SelectField("Stop", coerce=int, validators=[DataRequired()])
    date = DateField("Date", validators=[DataRequired()])
    submit = SubmitField("Add Stop Closure")


class PlantForm(FlaskForm):
    name = StringField("Plant Name", validators=[DataRequired(), Length(max=120)])
    address = StringField("Address", validators=[Optional(), Length(max=255)])
    latitude = FloatField("Latitude", validators=[Optional()])
    longitude = FloatField("Longitude", validators=[Optional()])
    loading_time_minutes = IntegerField(
        "Loading Time (minutes)", validators=[DataRequired(), NumberRange(min=0)]
    )
    shift_start_earliest = TimeField("Earliest Shift Start", validators=[DataRequired()])
    max_shift_minutes = IntegerField(
        "Max Shift Length (minutes)", validators=[DataRequired(), NumberRange(min=1)]
    )
    submit = SubmitField("Save Plant")

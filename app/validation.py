from datetime import date
from decimal import Decimal, InvalidOperation
import colorsys
import re

class ValidationError(ValueError):
    pass

def valid_date(value):
    try:
        parsed=date.fromisoformat(str(value))
        if parsed.isoformat()!=value: raise ValueError()
    except (ValueError,TypeError):
        raise ValidationError('日期必须为有效的 YYYY-MM-DD')
    return value

def cents(value,field='金额',nullable=False):
    if value is None and nullable: return None
    if isinstance(value,bool) or not isinstance(value,int) or abs(value)>10**14:
        raise ValidationError(f'{field}必须为整数分，且在允许范围内')
    return value

def money_to_cents(value,field='金额'):
    if isinstance(value,bool): raise ValidationError(f'{field}不是有效金额')
    try:
        d=Decimal(str(value))
        if not d.is_finite() or d*100!=(d*100).to_integral_value(): raise InvalidOperation()
        return cents(int(d*100),field)
    except (InvalidOperation,ValueError,TypeError,OverflowError):
        raise ValidationError(f'{field}请输入最多两位小数的金额')

def text(value,field,max_length=300,required=False):
    value='' if value is None else str(value).strip()
    if len(value)>max_length or (required and not value):
        raise ValidationError(f'{field}不能为空且长度不超过{max_length}字' if required else f'{field}长度不超过{max_length}字')
    return value

def price(value):
    try:
        d=Decimal(str(value))
        if not d.is_finite() or d<0 or d>10**9 or d.as_tuple().exponent < -8: raise InvalidOperation()
        return format(d,'f')
    except (InvalidOperation,ValueError,TypeError):
        raise ValidationError('价格应为非负数，最多8位小数')

def sector_color(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(value)):
        raise ValidationError('颜色应为 #RRGGBB')
    rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
    hue,light,sat=colorsys.rgb_to_hls(*rgb)
    hue*=360
    if sat>.18 and not (20<=hue<=65 or 190<=hue<=340):
        raise ValidationError('行业色可用鹅黄、粉色、橙金、蓝紫色系，请避开红绿')
    pastel=(40<=hue<=65 or 310<=hue<=340) and sat>.18
    if light>(.84 if pastel else .72) or light<.20: raise ValidationError('颜色过浅、过暗或接近黑色，请保持线条清晰')
    return value.upper()

import pytest
from pydantic import ValidationError
from cloudrun.schemas import CreateVideoRequest
from cloudrun.validation import validate
from cloudrun.errors import ApiError
from workflows.parameters import canvas, frame_count, validate_output


def test_omitted_defaults_match_explicit_request(request_body):
    implicit = {k:v for k,v in request_body.items() if k not in ('resolution','ratio','duration')}
    assert validate(CreateVideoRequest(**implicit)) == validate(CreateVideoRequest(**request_body))


@pytest.mark.parametrize('resolution,ratio,duration,size,frames', [
    ('768P','16:9',5,(1344,768),124),
    ('480P','9:16',4,(480,832),107),
    ('720P','1:1',1,(960,960),39),
    ('480P','16:9',15,(832,480),362),
    ('768P','adaptive',6,None,158),
])
def test_request_parameters_resolve(resolution,ratio,duration,size,frames,request_body):
    req={**request_body,'resolution':resolution,'ratio':ratio,'duration':duration}
    assert validate(CreateVideoRequest(**req)) == req
    assert canvas(resolution,ratio) == size
    assert frame_count(duration) == frames


@pytest.mark.parametrize('field,value,code', [
    ('resolution','1080P','UNSUPPORTED_RESOLUTION'),
    ('ratio','0:1','INVALID_RATIO_FOR_WORKFLOW'),
    ('duration',0,'UNSUPPORTED_DURATION'),
    ('duration',16,'UNSUPPORTED_DURATION'),
])
def test_invalid_parameters_rejected(field,value,code,request_body):
    with pytest.raises(ApiError) as error:
        validate(CreateVideoRequest(**{**request_body,field:value}))
    assert error.value.code==code


@pytest.mark.parametrize('value',[True,4.5,'5'])
def test_duration_is_strict_integer(value,request_body):
    with pytest.raises(ValidationError):CreateVideoRequest(**{**request_body,'duration':value})


def test_adaptive_and_reported_output_are_checked():
    assert canvas('768P','adaptive',(1376,768)) == (1344,768)
    assert canvas('480P','adaptive',(768,1376)) == (480,864)
    output={'width':480,'height':832,'fps':24,'frame_count':107,'duration_seconds':107/24}
    validate_output(output,'480P','9:16',4)
    for change in [{'width':832},{'frame_count':124},{'fps':30},{'duration_seconds':float('nan')}]:
        with pytest.raises(ValueError):validate_output({**output,**change},'480P','9:16',4)

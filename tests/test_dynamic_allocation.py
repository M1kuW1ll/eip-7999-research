from dynamics import ProportionalBundleCaps, SeparateResourceCaps


LIMITS = {"execution": 100, "data": 48, "state": None}
QUANTA = {"execution": 1, "data": 16, "state": 1}


def test_separate_caps_do_not_reduce_uncapped_or_unconstrained_resources():
    offered = {"execution": 80, "data": 64, "state": 200}

    allocation = SeparateResourceCaps().allocate(offered, LIMITS, QUANTA)

    assert allocation.included_gas == {
        "execution": 80,
        "data": 48,
        "state": 200,
    }
    assert allocation.unserved_gas == {
        "execution": 0,
        "data": 16,
        "state": 0,
    }
    assert allocation.binding_resources == ("data",)


def test_proportional_caps_preserve_fixed_bundle_recipe_approximately():
    offered = {"execution": 200, "data": 64, "state": 300}

    allocation = ProportionalBundleCaps().allocate(offered, LIMITS, QUANTA)

    assert allocation.bundle_scale == 0.5
    assert allocation.included_gas == {
        "execution": 100,
        "data": 32,
        "state": 150,
    }
    assert allocation.unserved_gas == {
        "execution": 100,
        "data": 32,
        "state": 150,
    }
    assert allocation.binding_resources == ("execution",)


def test_proportional_caps_do_nothing_when_no_limit_binds():
    offered = {"execution": 90, "data": 32, "state": 300}

    allocation = ProportionalBundleCaps().allocate(offered, LIMITS, QUANTA)

    assert allocation.bundle_scale == 1.0
    assert allocation.included_gas == offered


def test_proportional_caps_fill_binding_limit_without_float_underflow():
    offered = {"execution": 161, "data": 32, "state": 100}

    allocation = ProportionalBundleCaps().allocate(offered, LIMITS, QUANTA)

    assert allocation.included_gas["execution"] == 100
    assert allocation.binding_resources == ("execution",)


def test_limit_must_respect_resource_gas_quantum():
    limits = {"execution": 100, "data": 50, "state": None}

    try:
        SeparateResourceCaps().allocate(
            {"execution": 80, "data": 64, "state": 200},
            limits,
            QUANTA,
        )
    except ValueError as error:
        assert "divisible" in str(error)
    else:
        raise AssertionError("non-representable data limit must be rejected")
